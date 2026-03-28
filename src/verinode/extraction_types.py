from __future__ import annotations

from pydantic import BaseModel, Field

from verinode.models import CardType, ClaimKind, EvidenceSourceKind


class ExtractedEvidenceSpan(BaseModel):
    source_kind: EvidenceSourceKind = EvidenceSourceKind.DOCUMENT
    text: str
    page_label: str | None = None
    start_anchor: str | None = None
    end_anchor: str | None = None


class ExtractedReference(BaseModel):
    ref_label: str | None = None
    raw_citation: str
    resolved_title: str | None = None
    resolved_url: str | None = None
    resolved_doi: str | None = None
    relation_type: str = "cites"


class ExtractedClaimCard(BaseModel):
    card_type: CardType = CardType.CLAIM
    claim_kind: ClaimKind = ClaimKind.FACTUAL_CLAIM
    claim_text: str | None = None
    page_label: str | None = None
    section_label: str | None = None
    summary: str | None = None
    evidence_spans: list[ExtractedEvidenceSpan] = Field(default_factory=list)
    references: list[ExtractedReference] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    document_title: str | None = None
    cards: list[ExtractedClaimCard] = Field(default_factory=list)
