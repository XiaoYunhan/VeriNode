from __future__ import annotations

from pydantic import BaseModel

from verinode.models import TinyFishRunStatus


class WebEvidenceAcquisition(BaseModel):
    status: TinyFishRunStatus
    goal: str
    run_id: str | None = None
    source_url: str | None = None
    page_title: str | None = None
    evidence_snippet: str | None = None
    reasoning_summary: str | None = None
    screenshot_useful: bool | None = None
    screenshot_data_uri: str | None = None
    error_message: str | None = None
