from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from verinode.models import CardStage, ClaimCard, VerificationResultRecord
from verinode.verifiers.base import ReferenceVerifier


def run_card_verification(
    session: Session,
    *,
    card: ClaimCard,
    verifier: ReferenceVerifier,
) -> None:
    for result in list(
        session.scalars(
            select(VerificationResultRecord).where(
                VerificationResultRecord.claim_card_id == card.id
            )
        )
    ):
        session.delete(result)

    evidence_texts = [span.text for span in card.evidence_spans]

    for claim_reference in card.claim_references:
        reference = claim_reference.reference
        verdict = verifier.verify(
            document_title=card.document.title,
            claim_text=card.claim_text,
            claim_kind=card.claim_kind,
            card_summary=card.summary,
            evidence_spans=evidence_texts,
            ref_label=reference.ref_label,
            raw_citation=reference.raw_citation,
            resolved_title=reference.resolved_title,
            resolved_url=reference.resolved_url,
            resolved_doi=reference.resolved_doi,
        )
        session.add(
            VerificationResultRecord(
                id=uuid4().hex,
                claim_card_id=card.id,
                reference_id=reference.id,
                exists_verdict=verdict.exists_verdict,
                support_verdict=verdict.support_verdict,
                reasoning_summary=verdict.reasoning_summary,
                source_url=verdict.source_url,
            )
        )

    card.stage = CardStage.VERIFIED
