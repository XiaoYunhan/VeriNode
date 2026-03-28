from __future__ import annotations

from pydantic import BaseModel

from verinode.models import SandboxRunStatus


class SandboxExecutionResult(BaseModel):
    status: SandboxRunStatus
    summary: str
    full_process: str
    error_message: str | None = None
