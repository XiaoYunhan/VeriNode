from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from verinode.models import (
    CardStage,
    CardType,
    ClaimCard,
    EvidenceSourceKind,
    EvidenceSpan,
    SandboxRunRecord,
)
from verinode.sandbox_types import SandboxExecutionResult
from verinode.sandboxes.base import SandboxExecutor
from verinode.sandboxes.openai import render_sandbox_html


def run_card_sandbox(
    session: Session,
    *,
    data_dir: Path,
    card: ClaimCard,
    executor: SandboxExecutor,
) -> None:
    if card.card_type not in {CardType.CODE, CardType.MATH}:
        raise ValueError("card_not_sandboxable")

    result = executor.execute(
        document_title=card.document.title,
        card_type=card.card_type,
        claim_text=card.claim_text,
        card_summary=card.summary,
        evidence_spans=[span.text for span in card.evidence_spans],
    )
    artifact_path = _write_sandbox_artifact(
        data_dir=data_dir,
        card=card,
        result=result,
    )

    session.execute(
        delete(EvidenceSpan).where(
            EvidenceSpan.claim_card_id == card.id,
            EvidenceSpan.source_kind == EvidenceSourceKind.SANDBOX,
        )
    )

    session.add(
        SandboxRunRecord(
            id=uuid4().hex,
            claim_card_id=card.id,
            status=result.status,
            summary=result.summary,
            artifact_path=artifact_path,
        )
    )
    session.add(
        EvidenceSpan(
            id=uuid4().hex,
            claim_card_id=card.id,
            source_kind=EvidenceSourceKind.SANDBOX,
            text=result.summary,
            page_label=None,
            start_anchor=None,
            end_anchor=None,
        )
    )

    if result.error_message:
        raise ValueError(result.error_message)

    card.stage = CardStage.SANDBOXED


def _write_sandbox_artifact(
    *,
    data_dir: Path,
    card: ClaimCard,
    result: SandboxExecutionResult,
) -> str:
    sandbox_dir = data_dir / "artifacts" / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{card.id}-{uuid4().hex}.html"
    target_path = sandbox_dir / filename
    html = render_sandbox_html(
        title=card.summary or card.claim_text or "Sandbox Run",
        summary=result.summary,
        process=result.full_process,
    )
    target_path.write_text(html, encoding="utf-8")
    return str(Path("artifacts") / "sandbox" / filename)
