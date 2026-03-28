from __future__ import annotations

import re


DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
ARXIV_URL_PATTERN = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(?P<identifier>[A-Za-z0-9.\-]+(?:/[A-Za-z0-9.\-]+)?(?:v\d+)?)",
    re.IGNORECASE,
)
ARXIV_TEXT_PATTERN = re.compile(
    r"(?:arxiv\s*:?\s*)(?P<identifier>[A-Za-z0-9.\-]+(?:/[A-Za-z0-9.\-]+)?(?:v\d+)?)",
    re.IGNORECASE,
)


def normalize_reference(
    *,
    raw_citation: str,
    resolved_title: str | None,
    resolved_url: str | None,
    resolved_doi: str | None,
) -> dict[str, str | None]:
    doi = resolved_doi or _extract_doi(raw_citation) or _extract_doi(resolved_url or "")
    arxiv_id = _extract_arxiv_id(resolved_url or "") or _extract_arxiv_id(raw_citation)
    normalized_url = resolved_url or _url_from_doi(doi) or _url_from_arxiv(arxiv_id)

    return {
        "resolved_title": resolved_title,
        "resolved_url": normalized_url,
        "resolved_doi": doi,
    }


def build_evidence_target_url(
    source_url: str | None,
    *,
    raw_citation: str | None = None,
) -> str | None:
    arxiv_id = _extract_arxiv_id(source_url or "") or _extract_arxiv_id(raw_citation or "")
    if arxiv_id:
        return _pdf_url_from_arxiv(arxiv_id)
    return source_url


def _extract_doi(text: str) -> str | None:
    match = DOI_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_arxiv_id(text: str) -> str | None:
    match = ARXIV_URL_PATTERN.search(text)
    if match:
        return match.group("identifier").removesuffix(".pdf")

    match = ARXIV_TEXT_PATTERN.search(text)
    if match:
        return match.group("identifier")
    return None


def _url_from_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return f"https://doi.org/{doi}"


def _url_from_arxiv(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    return f"https://arxiv.org/abs/{arxiv_id}"


def _pdf_url_from_arxiv(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
