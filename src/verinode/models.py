from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from verinode.database import Base, utcnow


class FileType(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


class CardType(StrEnum):
    CLAIM = "claim"
    CODE = "code"
    MATH = "math"


class ClaimKind(StrEnum):
    FACTUAL_CLAIM = "factual_claim"
    OPINION_OR_INTERPRETATION = "opinion_or_interpretation"
    METHOD_DESCRIPTION = "method_description"
    RESULT_CLAIM = "result_claim"
    CODE_MATH_ARTIFACT = "code_math_artifact"


class EvidenceSourceKind(StrEnum):
    DOCUMENT = "document"
    REFERENCE = "reference"
    TINYFISH = "tinyfish"
    EXTERNAL_SEARCH = "external_search"
    SANDBOX = "sandbox"


class CardStage(StrEnum):
    DRAFT = "draft"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    WEB_EVIDENCE_ACQUIRED = "web_evidence_acquired"
    EXTERNALLY_CHECKED = "externally_checked"
    SANDBOXED = "sandboxed"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    EXTRACT_CLAIMS = "extract_claims"
    VERIFY_CARD = "verify_card"
    WEB_EVIDENCE = "web_evidence"
    EXTERNAL_SEARCH = "external_search"
    SANDBOX = "sandbox"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReferenceExistenceVerdict(StrEnum):
    EXISTS = "exists"
    NOT_FOUND = "not_found"
    CANNOT_DETERMINE = "cannot_determine"


class SupportVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    CANNOT_VERIFY = "cannot_verify"


class TinyFishRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(Enum(FileType, native_enum=False))
    storage_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False),
        default=DocumentStatus.UPLOADED,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    claim_cards: Mapped[list["ClaimCard"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    references: Mapped[list["ReferenceRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="document")


class ClaimCard(Base):
    __tablename__ = "claim_cards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    card_type: Mapped[CardType] = mapped_column(Enum(CardType, native_enum=False))
    claim_kind: Mapped[ClaimKind] = mapped_column(
        Enum(ClaimKind, native_enum=False),
        default=ClaimKind.FACTUAL_CLAIM,
    )
    claim_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[CardStage] = mapped_column(
        Enum(CardStage, native_enum=False),
        default=CardStage.DRAFT,
    )
    page_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    document: Mapped[Document] = relationship(back_populates="claim_cards")
    evidence_spans: Mapped[list["EvidenceSpan"]] = relationship(
        back_populates="claim_card",
        cascade="all, delete-orphan",
    )
    claim_references: Mapped[list["ClaimReference"]] = relationship(
        back_populates="claim_card",
        cascade="all, delete-orphan",
    )
    verification_results: Mapped[list["VerificationResultRecord"]] = relationship(
        back_populates="claim_card",
        cascade="all, delete-orphan",
    )
    tinyfish_runs: Mapped[list["TinyFishRunRecord"]] = relationship(
        back_populates="claim_card",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="claim_card")

    @property
    def references(self) -> list["ClaimReference"]:
        return self.claim_references


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_card_id: Mapped[str] = mapped_column(ForeignKey("claim_cards.id"), index=True)
    source_kind: Mapped[EvidenceSourceKind] = mapped_column(
        Enum(EvidenceSourceKind, native_enum=False),
    )
    text: Mapped[str] = mapped_column(Text)
    page_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_anchor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_anchor: Mapped[str | None] = mapped_column(String(255), nullable=True)

    claim_card: Mapped[ClaimCard] = relationship(back_populates="evidence_spans")


class ReferenceRecord(Base):
    __tablename__ = "references"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    ref_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_citation: Mapped[str] = mapped_column(Text)
    resolved_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resolved_doi: Mapped[str | None] = mapped_column(String(128), nullable=True)

    document: Mapped[Document] = relationship(back_populates="references")
    claim_links: Mapped[list["ClaimReference"]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
    )
    verification_results: Mapped[list["VerificationResultRecord"]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
    )
    tinyfish_runs: Mapped[list["TinyFishRunRecord"]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
    )


class ClaimReference(Base):
    __tablename__ = "claim_references"

    claim_card_id: Mapped[str] = mapped_column(
        ForeignKey("claim_cards.id"),
        primary_key=True,
    )
    reference_id: Mapped[str] = mapped_column(
        ForeignKey("references.id"),
        primary_key=True,
    )
    relation_type: Mapped[str] = mapped_column(String(64), default="cites")

    claim_card: Mapped[ClaimCard] = relationship(back_populates="claim_references")
    reference: Mapped[ReferenceRecord] = relationship(back_populates="claim_links")


class VerificationResultRecord(Base):
    __tablename__ = "verification_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_card_id: Mapped[str] = mapped_column(ForeignKey("claim_cards.id"), index=True)
    reference_id: Mapped[str] = mapped_column(ForeignKey("references.id"), index=True)
    exists_verdict: Mapped[ReferenceExistenceVerdict] = mapped_column(
        Enum(ReferenceExistenceVerdict, native_enum=False),
    )
    support_verdict: Mapped[SupportVerdict] = mapped_column(
        Enum(SupportVerdict, native_enum=False),
    )
    reasoning_summary: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim_card: Mapped[ClaimCard] = relationship(back_populates="verification_results")
    reference: Mapped[ReferenceRecord] = relationship(back_populates="verification_results")


class TinyFishRunRecord(Base):
    __tablename__ = "tinyfish_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_card_id: Mapped[str] = mapped_column(ForeignKey("claim_cards.id"), index=True)
    reference_id: Mapped[str] = mapped_column(ForeignKey("references.id"), index=True)
    status: Mapped[TinyFishRunStatus] = mapped_column(
        Enum(TinyFishRunStatus, native_enum=False),
    )
    goal: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim_card: Mapped[ClaimCard] = relationship(back_populates="tinyfish_runs")
    reference: Mapped[ReferenceRecord] = relationship(back_populates="tinyfish_runs")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, native_enum=False))
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"),
        index=True,
        nullable=True,
    )
    claim_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("claim_cards.id"),
        index=True,
        nullable=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False),
        default=JobStatus.QUEUED,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    document: Mapped[Document | None] = relationship(back_populates="jobs")
    claim_card: Mapped[ClaimCard | None] = relationship(back_populates="jobs")
