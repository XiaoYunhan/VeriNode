from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from verinode.models import (
    CardStage,
    CardType,
    ClaimKind,
    DocumentStatus,
    EvidenceSourceKind,
    FileType,
    JobStatus,
    JobType,
    ReferenceExistenceVerdict,
    SupportVerdict,
    TinyFishRunStatus,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentRead(ApiModel):
    id: str
    filename: str
    file_type: FileType
    storage_path: str
    status: DocumentStatus
    title: str | None
    created_at: datetime
    updated_at: datetime


class ClaimCardRead(ApiModel):
    id: str
    document_id: str
    card_type: CardType
    claim_kind: ClaimKind
    claim_text: str | None
    stage: CardStage
    page_label: str | None
    section_label: str | None
    summary: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceSpanRead(ApiModel):
    id: str
    source_kind: EvidenceSourceKind
    text: str
    page_label: str | None
    start_anchor: str | None
    end_anchor: str | None


class ReferenceRead(ApiModel):
    id: str
    ref_label: str | None
    raw_citation: str
    resolved_title: str | None
    resolved_url: str | None
    resolved_doi: str | None


class ClaimReferenceRead(ApiModel):
    relation_type: str
    reference: ReferenceRead


class VerificationResultRead(ApiModel):
    id: str
    exists_verdict: ReferenceExistenceVerdict
    support_verdict: SupportVerdict
    reasoning_summary: str
    source_url: str | None
    created_at: datetime
    reference: ReferenceRead


class TinyFishRunRead(ApiModel):
    id: str
    status: TinyFishRunStatus
    goal: str
    run_id: str | None
    source_url: str | None
    result_summary: str | None
    artifact_path: str | None
    created_at: datetime
    reference: ReferenceRead


class ClaimCardDetailRead(ClaimCardRead):
    evidence_spans: list[EvidenceSpanRead]
    references: list[ClaimReferenceRead]
    verification_results: list[VerificationResultRead]
    tinyfish_runs: list[TinyFishRunRead]


class JobRead(ApiModel):
    id: str
    job_type: JobType
    document_id: str | None
    claim_card_id: str | None
    status: JobStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime
