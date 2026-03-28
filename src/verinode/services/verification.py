from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from verinode.acquirers.base import WebEvidenceAcquirer
from verinode.models import (
    CardStage,
    ClaimCard,
    ClaimReference,
    ReferenceRecord,
    VerificationResultRecord,
)
from verinode.services.web_evidence import (
    acquire_reference_web_evidence,
    clear_card_web_evidence,
    persist_reference_web_evidence,
)
from verinode.verifiers.base import ReferenceVerifier
from verinode.verification_types import ReferenceVerificationResult
from verinode.web_evidence_types import WebEvidenceAcquisition


@dataclass(slots=True)
class PreparedClaimReference:
    reference_id: str
    relation_type: str
    ref_label: str | None
    raw_citation: str
    resolved_title: str | None
    resolved_url: str | None
    resolved_doi: str | None
    existing_reference: ReferenceRecord | None = None


@dataclass(slots=True)
class PreparedVerificationOutcome:
    prepared_reference: PreparedClaimReference
    verdict: ReferenceVerificationResult
    acquisition: WebEvidenceAcquisition | None = None


def run_card_verification(
    session: Session,
    *,
    data_dir: Path,
    card: ClaimCard,
    verifier: ReferenceVerifier,
    web_evidence_acquirer: WebEvidenceAcquirer | None = None,
) -> None:
    evidence_texts = [span.text for span in card.evidence_spans]
    prepared_references = _prepare_claim_references(card=card)
    outcomes: list[PreparedVerificationOutcome] = []

    for prepared_reference in prepared_references:
        verdict = verifier.verify(
            document_title=card.document.title,
            claim_text=card.claim_text,
            claim_kind=card.claim_kind,
            card_summary=card.summary,
            evidence_spans=evidence_texts,
            relation_type=prepared_reference.relation_type,
            ref_label=prepared_reference.ref_label,
            raw_citation=prepared_reference.raw_citation,
            resolved_title=prepared_reference.resolved_title,
            resolved_url=prepared_reference.resolved_url,
            resolved_doi=prepared_reference.resolved_doi,
        )

        acquisition = None
        if web_evidence_acquirer is not None:
            materialized_reference = (
                prepared_reference.existing_reference
                or ReferenceRecord(
                    id=prepared_reference.reference_id,
                    document_id=card.document_id,
                    ref_label=prepared_reference.ref_label,
                    raw_citation=prepared_reference.raw_citation,
                    resolved_title=prepared_reference.resolved_title,
                    resolved_url=prepared_reference.resolved_url,
                    resolved_doi=prepared_reference.resolved_doi,
                )
            )
            acquisition = acquire_reference_web_evidence(
                card=card,
                reference=materialized_reference,
                source_url=verdict.source_url or prepared_reference.resolved_url,
                acquirer=web_evidence_acquirer,
            )
        outcomes.append(
            PreparedVerificationOutcome(
                prepared_reference=prepared_reference,
                verdict=verdict,
                acquisition=acquisition,
            )
        )

    session.execute(
        delete(VerificationResultRecord).where(
            VerificationResultRecord.claim_card_id == card.id
        )
    )
    clear_card_web_evidence(session, card=card)

    completed_web_evidence = False
    for outcome in outcomes:
        reference = _materialize_prepared_reference(
            session,
            card=card,
            prepared_reference=outcome.prepared_reference,
        )
        session.add(
            VerificationResultRecord(
                id=uuid4().hex,
                claim_card_id=card.id,
                reference_id=reference.id,
                exists_verdict=outcome.verdict.exists_verdict,
                support_verdict=outcome.verdict.support_verdict,
                reasoning_summary=outcome.verdict.reasoning_summary,
                source_url=outcome.verdict.source_url,
            )
        )
        if outcome.acquisition is not None:
            completed_web_evidence = persist_reference_web_evidence(
                session,
                data_dir=data_dir,
                card=card,
                reference=reference,
                acquisition=outcome.acquisition,
                soft_fail=True,
            ) or completed_web_evidence

    card.stage = (
        CardStage.WEB_EVIDENCE_ACQUIRED
        if completed_web_evidence
        else CardStage.VERIFIED
    )


def _prepare_claim_references(*, card: ClaimCard) -> list[PreparedClaimReference]:
    if card.claim_references:
        return [
            PreparedClaimReference(
                reference_id=claim_reference.reference.id,
                relation_type=claim_reference.relation_type,
                ref_label=claim_reference.reference.ref_label,
                raw_citation=claim_reference.reference.raw_citation,
                resolved_title=claim_reference.reference.resolved_title,
                resolved_url=claim_reference.reference.resolved_url,
                resolved_doi=claim_reference.reference.resolved_doi,
                existing_reference=claim_reference.reference,
            )
            for claim_reference in card.claim_references
        ]

    lookup_text = _build_lookup_query(card)
    return [
        PreparedClaimReference(
            reference_id=uuid4().hex,
            relation_type="internet_lookup",
            ref_label=None,
            raw_citation=lookup_text,
            resolved_title=None,
            resolved_url=None,
            resolved_doi=None,
            existing_reference=None,
        )
    ]


def _materialize_prepared_reference(
    session: Session,
    *,
    card: ClaimCard,
    prepared_reference: PreparedClaimReference,
) -> ReferenceRecord:
    if prepared_reference.existing_reference is not None:
        return prepared_reference.existing_reference

    reference = ReferenceRecord(
        id=prepared_reference.reference_id,
        document_id=card.document_id,
        ref_label=prepared_reference.ref_label,
        raw_citation=prepared_reference.raw_citation,
        resolved_title=prepared_reference.resolved_title,
        resolved_url=prepared_reference.resolved_url,
        resolved_doi=prepared_reference.resolved_doi,
    )
    session.add(reference)
    session.add(
        ClaimReference(
            claim_card_id=card.id,
            reference_id=reference.id,
            relation_type=prepared_reference.relation_type,
        )
    )
    prepared_reference.existing_reference = reference
    return reference


def _build_lookup_query(card: ClaimCard) -> str:
    summary = (card.summary or "").strip()
    claim_text = (card.claim_text or "").strip()
    title = (card.document.title or "").strip()
    if summary and title:
        return f"{summary} ({title})"
    if summary:
        return summary
    if claim_text and title:
        return f"{claim_text} ({title})"
    if claim_text:
        return claim_text
    if title:
        return title
    return f"Verification lookup for card {card.id}"
