from __future__ import annotations

from typing import Protocol

from verinode.models import ClaimKind
from verinode.verification_types import ReferenceVerificationResult


class ReferenceVerifier(Protocol):
    def verify(
        self,
        *,
        document_title: str | None,
        claim_text: str | None,
        claim_kind: ClaimKind,
        card_summary: str | None,
        evidence_spans: list[str],
        ref_label: str | None,
        raw_citation: str,
        resolved_title: str | None,
        resolved_url: str | None,
        resolved_doi: str | None,
    ) -> ReferenceVerificationResult: ...

