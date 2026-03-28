from __future__ import annotations

from pydantic import BaseModel

from verinode.models import ReferenceExistenceVerdict, SupportVerdict


class ReferenceVerificationResult(BaseModel):
    exists_verdict: ReferenceExistenceVerdict
    support_verdict: SupportVerdict
    reasoning_summary: str
    source_url: str | None = None

