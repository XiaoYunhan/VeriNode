from __future__ import annotations

from verinode.services.references import normalize_reference


def test_normalize_reference_builds_doi_url_when_missing() -> None:
    normalized = normalize_reference(
        raw_citation="Example Paper. doi:10.48550/arXiv.1706.03762",
        resolved_title=None,
        resolved_url=None,
        resolved_doi=None,
    )

    assert normalized["resolved_doi"] == "10.48550/arXiv.1706.03762"
    assert normalized["resolved_url"] == "https://doi.org/10.48550/arXiv.1706.03762"


def test_normalize_reference_builds_arxiv_url_when_missing() -> None:
    normalized = normalize_reference(
        raw_citation="Quantum Amplitude Amplification and Estimation. arXiv:quant-ph/0005055",
        resolved_title=None,
        resolved_url=None,
        resolved_doi=None,
    )

    assert normalized["resolved_doi"] is None
    assert normalized["resolved_url"] == "https://arxiv.org/abs/quant-ph/0005055"
