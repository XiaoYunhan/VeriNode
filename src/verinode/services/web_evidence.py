from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from verinode.acquirers.base import WebEvidenceAcquirer
from verinode.models import (
    CardStage,
    ClaimCard,
    EvidenceSourceKind,
    EvidenceSpan,
    ReferenceRecord,
    TinyFishRunRecord,
    TinyFishRunStatus,
)
from verinode.web_evidence_types import WebEvidenceAcquisition


def clear_card_web_evidence(session: Session, *, card: ClaimCard) -> None:
    session.execute(
        delete(EvidenceSpan).where(
            EvidenceSpan.claim_card_id == card.id,
            EvidenceSpan.source_kind == EvidenceSourceKind.TINYFISH,
        )
    )


def capture_reference_web_evidence(
    session: Session,
    *,
    data_dir: Path,
    card: ClaimCard,
    reference: ReferenceRecord,
    source_url: str | None,
    acquirer: WebEvidenceAcquirer,
    soft_fail: bool,
) -> bool:
    acquisition = acquire_reference_web_evidence(
        card=card,
        reference=reference,
        source_url=source_url,
        acquirer=acquirer,
    )
    return persist_reference_web_evidence(
        session,
        data_dir=data_dir,
        card=card,
        reference=reference,
        acquisition=acquisition,
        soft_fail=soft_fail,
    )


def acquire_reference_web_evidence(
    *,
    card: ClaimCard,
    reference: ReferenceRecord,
    source_url: str | None,
    acquirer: WebEvidenceAcquirer,
) -> WebEvidenceAcquisition:
    if not source_url:
        return WebEvidenceAcquisition(
            status=TinyFishRunStatus.FAILED,
            goal=f"Blocked web evidence capture for {reference.raw_citation}",
            source_url=None,
            error_message="Blocked: no usable source URL was available for browser evidence.",
        )

    try:
        return acquirer.acquire(
            document_title=card.document.title,
            claim_text=card.claim_text,
            card_summary=card.summary,
            reference_label=reference.ref_label,
            raw_citation=reference.raw_citation,
            source_url=source_url,
        )
    except Exception as exc:
        return WebEvidenceAcquisition(
            status=TinyFishRunStatus.FAILED,
            goal=f"Inspect browser evidence for {reference.raw_citation}",
            source_url=source_url,
            error_message=str(exc),
        )


def persist_reference_web_evidence(
    session: Session,
    *,
    data_dir: Path,
    card: ClaimCard,
    reference: ReferenceRecord,
    acquisition: WebEvidenceAcquisition,
    soft_fail: bool,
) -> bool:
    tinyfish_dir = data_dir / "artifacts" / "tinyfish"
    tinyfish_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = _write_screenshot_artifact(
        screenshot_data_uri=acquisition.screenshot_data_uri,
        artifacts_dir=tinyfish_dir,
        run_id=acquisition.run_id,
    )
    effective_status, summary = _normalize_acquisition_outcome(
        acquisition=acquisition,
        artifact_path=artifact_path,
    )

    session.add(
        TinyFishRunRecord(
            id=uuid4().hex,
            claim_card_id=card.id,
            reference_id=reference.id,
            status=effective_status,
            goal=acquisition.goal,
            run_id=acquisition.run_id,
            source_url=acquisition.source_url,
            result_summary=summary,
            artifact_path=artifact_path,
        )
    )

    if effective_status is not TinyFishRunStatus.COMPLETED:
        if soft_fail:
            return False
        raise ValueError(summary or acquisition.error_message or "tinyfish_web_evidence_failed")

    if acquisition.evidence_snippet:
        session.add(
            EvidenceSpan(
                id=uuid4().hex,
                claim_card_id=card.id,
                source_kind=EvidenceSourceKind.TINYFISH,
                text=acquisition.evidence_snippet,
                page_label=None,
                start_anchor=None,
                end_anchor=None,
            )
        )
    return True


def _normalize_acquisition_outcome(
    *,
    acquisition: WebEvidenceAcquisition,
    artifact_path: str | None,
) -> tuple[TinyFishRunStatus, str | None]:
    summary = _summarize_acquisition(acquisition)
    if acquisition.status is not TinyFishRunStatus.COMPLETED:
        return acquisition.status, summary
    if not artifact_path:
        return (
            TinyFishRunStatus.FAILED,
            _combine_blocked_summary(
                "Blocked: TinyFish reached the page but did not return a screenshot artifact.",
                summary,
            ),
        )
    if acquisition.screenshot_useful is False:
        return (
            TinyFishRunStatus.FAILED,
            _combine_blocked_summary(
                "Blocked: TinyFish did not identify a screenshot that directly supports the claim.",
                summary,
            ),
        )
    return TinyFishRunStatus.COMPLETED, summary


def _combine_blocked_summary(prefix: str, summary: str | None) -> str:
    if summary and summary.strip():
        return f"{prefix} {summary.strip()}"
    return prefix


def run_card_web_evidence(
    session: Session,
    *,
    data_dir: Path,
    card: ClaimCard,
    acquirer: WebEvidenceAcquirer,
) -> None:
    references = [link.reference for link in card.claim_references]
    if not references:
        raise ValueError("card_has_no_resolved_references")

    latest_source_urls = {
        result.reference_id: result.source_url
        for result in card.verification_results
        if result.source_url
    }

    acquisitions = [
        (
            reference,
            acquire_reference_web_evidence(
                card=card,
                reference=reference,
                source_url=latest_source_urls.get(reference.id) or reference.resolved_url,
                acquirer=acquirer,
            ),
        )
        for reference in references
    ]

    completed_any = False
    clear_card_web_evidence(session, card=card)
    for reference, acquisition in acquisitions:
        completed_any = persist_reference_web_evidence(
            session,
            data_dir=data_dir,
            card=card,
            reference=reference,
            acquisition=acquisition,
            soft_fail=False,
        ) or completed_any

    card.stage = (
        CardStage.WEB_EVIDENCE_ACQUIRED
        if completed_any
        else CardStage.VERIFIED
    )


def _summarize_acquisition(acquisition: object) -> str | None:
    from verinode.web_evidence_types import WebEvidenceAcquisition

    if not isinstance(acquisition, WebEvidenceAcquisition):
        return None

    if acquisition.error_message:
        return acquisition.error_message

    parts = [
        acquisition.page_title,
        acquisition.reasoning_summary,
        acquisition.evidence_snippet,
    ]
    summary = " ".join(part.strip() for part in parts if part and part.strip())
    return summary or None


def _write_screenshot_artifact(
    *,
    screenshot_data_uri: str | None,
    artifacts_dir: Path,
    run_id: str | None,
) -> str | None:
    if not screenshot_data_uri or not screenshot_data_uri.startswith("data:image/"):
        return None

    header, _, encoded = screenshot_data_uri.partition(",")
    if not encoded:
        return None

    extension = ".jpg"
    if header.startswith("data:image/png"):
        extension = ".png"

    filename = f"{run_id or uuid4().hex}{extension}"
    target_path = artifacts_dir / filename
    target_path.write_bytes(base64.b64decode(encoded))
    return str(Path("artifacts") / "tinyfish" / filename)
