from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from verinode.extraction_types import ExtractionResult
from verinode.extractors.base import ClaimExtractor
from verinode.models import (
    CardStage,
    ClaimCard,
    Document,
    DocumentStatus,
    EvidenceSpan,
    ReferenceRecord,
    ClaimReference,
)
from verinode.services.references import normalize_reference


def run_document_extraction(
    session: Session,
    *,
    data_dir: Path,
    document: Document,
    extractor: ClaimExtractor,
) -> None:
    content = (data_dir / document.storage_path).read_bytes()
    extraction = extractor.extract(
        filename=document.filename,
        file_type=document.file_type,
        content=content,
    )
    replace_document_extraction(session, document=document, extraction=extraction)


def replace_document_extraction(
    session: Session,
    *,
    document: Document,
    extraction: ExtractionResult,
) -> None:
    for card in list(
        session.scalars(select(ClaimCard).where(ClaimCard.document_id == document.id))
    ):
        session.delete(card)

    for reference in list(
        session.scalars(
            select(ReferenceRecord).where(ReferenceRecord.document_id == document.id)
        )
    ):
        session.delete(reference)

    reference_cache: dict[tuple[str | None, str], ReferenceRecord] = {}

    for card_data in extraction.cards:
        card = ClaimCard(
            id=uuid4().hex,
            document_id=document.id,
            card_type=card_data.card_type,
            claim_kind=card_data.claim_kind,
            claim_text=card_data.claim_text,
            stage=CardStage.EXTRACTED,
            page_label=card_data.page_label,
            section_label=card_data.section_label,
            summary=card_data.summary,
        )
        session.add(card)

        for span_data in card_data.evidence_spans:
            session.add(
                EvidenceSpan(
                    id=uuid4().hex,
                    claim_card_id=card.id,
                    source_kind=span_data.source_kind,
                    text=span_data.text,
                    page_label=span_data.page_label,
                    start_anchor=span_data.start_anchor,
                    end_anchor=span_data.end_anchor,
                )
            )

        for reference_data in card_data.references:
            key = (reference_data.ref_label, reference_data.raw_citation)
            reference = reference_cache.get(key)
            if reference is None:
                normalized_reference = normalize_reference(
                    raw_citation=reference_data.raw_citation,
                    resolved_title=reference_data.resolved_title,
                    resolved_url=reference_data.resolved_url,
                    resolved_doi=reference_data.resolved_doi,
                )
                reference = ReferenceRecord(
                    id=uuid4().hex,
                    document_id=document.id,
                    ref_label=reference_data.ref_label,
                    raw_citation=reference_data.raw_citation,
                    resolved_title=normalized_reference["resolved_title"],
                    resolved_url=normalized_reference["resolved_url"],
                    resolved_doi=normalized_reference["resolved_doi"],
                )
                reference_cache[key] = reference
                session.add(reference)

            session.add(
                ClaimReference(
                    claim_card_id=card.id,
                    reference_id=reference.id,
                    relation_type=reference_data.relation_type,
                )
            )

    document.title = extraction.document_title or document.title
    document.status = DocumentStatus.READY
