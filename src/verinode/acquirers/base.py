from __future__ import annotations

from typing import Protocol

from verinode.web_evidence_types import WebEvidenceAcquisition


class WebEvidenceAcquirer(Protocol):
    def acquire(
        self,
        *,
        document_title: str | None,
        claim_text: str | None,
        card_summary: str | None,
        reference_label: str | None,
        raw_citation: str,
        source_url: str,
    ) -> WebEvidenceAcquisition: ...
