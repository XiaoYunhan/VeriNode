from __future__ import annotations

from typing import Protocol

from verinode.models import CardType
from verinode.sandbox_types import SandboxExecutionResult


class SandboxExecutor(Protocol):
    def execute(
        self,
        *,
        document_title: str | None,
        card_type: CardType,
        claim_text: str | None,
        card_summary: str | None,
        evidence_spans: list[str],
    ) -> SandboxExecutionResult: ...
