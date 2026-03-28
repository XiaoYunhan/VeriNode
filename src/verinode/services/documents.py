from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from verinode.models import ClaimCard, Document, DocumentStatus, FileType

MARKDOWN_SUFFIXES = {".md", ".markdown"}


def detect_file_type(filename: str) -> FileType | None:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return FileType.PDF
    if suffix in MARKDOWN_SUFFIXES:
        return FileType.MARKDOWN
    return None


def create_document(
    session: Session,
    *,
    uploads_dir: Path,
    filename: str,
    contents: bytes,
) -> Document:
    clean_name = Path(filename).name or "document"
    file_type = detect_file_type(clean_name)
    if file_type is None:
        raise ValueError("unsupported_file_type")

    document_id = uuid4().hex
    suffix = Path(clean_name).suffix.lower()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    relative_path = Path("uploads") / f"{document_id}{suffix}"
    full_path = uploads_dir / f"{document_id}{suffix}"
    full_path.write_bytes(contents)

    document = Document(
        id=document_id,
        filename=clean_name,
        file_type=file_type,
        storage_path=relative_path.as_posix(),
        status=DocumentStatus.UPLOADED,
        title=Path(clean_name).stem or None,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def list_document_cards(session: Session, document_id: str) -> list[ClaimCard]:
    statement = (
        select(ClaimCard)
        .where(ClaimCard.document_id == document_id)
        .order_by(ClaimCard.created_at.asc())
    )
    return list(session.scalars(statement))


def list_documents(session: Session) -> list[Document]:
    statement = select(Document).order_by(Document.created_at.desc())
    return list(session.scalars(statement))
