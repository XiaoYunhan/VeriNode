from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from verinode.acquirers.base import WebEvidenceAcquirer
from verinode.models import CardStage, ClaimCard, EvidenceSourceKind, EvidenceSpan, TinyFishRunRecord


def run_card_web_evidence(
    session: Session,
    *,
    data_dir: Path,
    card: ClaimCard,
    acquirer: WebEvidenceAcquirer,
) -> None:
    references = [link.reference for link in card.claim_references if link.reference.resolved_url]
    if not references:
        raise ValueError("card_has_no_resolved_references")

    session.execute(
        delete(EvidenceSpan).where(
            EvidenceSpan.claim_card_id == card.id,
            EvidenceSpan.source_kind == EvidenceSourceKind.TINYFISH,
        )
    )

    tinyfish_dir = data_dir / "artifacts" / "tinyfish"
    tinyfish_dir.mkdir(parents=True, exist_ok=True)

    for reference in references:
        acquisition = acquirer.acquire(
            document_title=card.document.title,
            claim_text=card.claim_text,
            card_summary=card.summary,
            reference_label=reference.ref_label,
            raw_citation=reference.raw_citation,
            source_url=reference.resolved_url or "",
        )

        artifact_path = _write_screenshot_artifact(
            screenshot_data_uri=acquisition.screenshot_data_uri,
            artifacts_dir=tinyfish_dir,
            run_id=acquisition.run_id,
        )
        summary = _summarize_acquisition(acquisition)

        session.add(
            TinyFishRunRecord(
                id=uuid4().hex,
                claim_card_id=card.id,
                reference_id=reference.id,
                status=acquisition.status,
                goal=acquisition.goal,
                run_id=acquisition.run_id,
                source_url=acquisition.source_url,
                result_summary=summary,
                artifact_path=artifact_path,
            )
        )

        if acquisition.status.value != "completed":
            raise ValueError(acquisition.error_message or "tinyfish_web_evidence_failed")

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

    card.stage = CardStage.WEB_EVIDENCE_ACQUIRED


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
