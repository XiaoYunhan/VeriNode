from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from verinode.acquirers.tinyfish import TinyFishWebEvidenceAcquirer
from verinode.clients.tinyfish import TinyFishClient
from verinode.extractors.openai import OpenAIClaimExtractor
from verinode.models import (
    CardType,
    ClaimKind,
    ReferenceExistenceVerdict,
    SupportVerdict,
    TinyFishRunStatus,
)
from verinode.services.documents import detect_file_type
from verinode.settings import Settings
from verinode.verifiers.openai import OpenAIReferenceVerifier

pytestmark = [pytest.mark.integration, pytest.mark.live]

LIVE_TEST_ENV = "VERINODE_RUN_LIVE_TESTS"
SAMPLE_DIR = Path(__file__).resolve().parents[1] / "resources" / "sample"
SAMPLE_FILES = [
    SAMPLE_DIR / "QMC.md",
    SAMPLE_DIR / "AmericanPutCallSymmetry_PeterCarr.pdf",
    SAMPLE_DIR / "1706.03762v7.pdf",
]


def require_live_tests() -> None:
    if os.getenv(LIVE_TEST_ENV) != "1":
        pytest.skip(
            f"Set {LIVE_TEST_ENV}=1 to run live OpenAI and TinyFish integration checks.",
        )


def load_settings() -> Settings:
    return Settings()


def parse_tinyfish_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    raise AssertionError(f"Unexpected TinyFish result type: {type(value)!r}")


@pytest.mark.parametrize("sample_path", SAMPLE_FILES, ids=[path.name for path in SAMPLE_FILES])
def test_openai_extractor_smoke_on_sample_documents(sample_path: Path) -> None:
    require_live_tests()
    settings = load_settings()
    extractor = OpenAIClaimExtractor(
        api_key=settings.openai_api_key,
        model=settings.openai_model_main,
    )

    file_type = detect_file_type(sample_path.name)
    assert file_type is not None

    result = extractor.extract(
        filename=sample_path.name,
        file_type=file_type,
        content=sample_path.read_bytes(),
    )

    assert result.cards, f"{sample_path.name}: no cards returned"
    assert any(card.claim_text or card.summary for card in result.cards), (
        f"{sample_path.name}: cards did not contain usable text fields"
    )
    assert any(card.evidence_spans for card in result.cards), (
        f"{sample_path.name}: no evidence spans were extracted"
    )

    for card in result.cards:
        assert card.card_type in {CardType.CLAIM, CardType.CODE, CardType.MATH}
        assert card.claim_text or card.summary, (
            f"{sample_path.name}: card missing claim_text and summary"
        )
        for span in card.evidence_spans:
            assert span.text.strip(), f"{sample_path.name}: evidence span text was empty"


def test_tinyfish_async_smoke_for_reference_style_probe() -> None:
    require_live_tests()
    settings = load_settings()
    client = TinyFishClient(
        api_key=settings.tinyfish_api_key,
        base_url=settings.tinyfish_base_url,
    )

    started = client.run_async(
        url="https://arxiv.org/abs/1706.03762",
        goal=(
            "Open the page and return JSON only with keys "
            "source_url, page_title, evidence_snippet, and screenshot_useful. "
            "Keep evidence_snippet under 50 words."
        ),
    )
    run_id = started.get("run_id")
    assert run_id, "TinyFish did not return a run_id"

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        batch = client.get_runs_batch(run_ids=[run_id])
        data = batch.get("data") or []
        assert data, "TinyFish batch lookup returned no run data"
        run = data[0]
        status = run.get("status")

        if status == "COMPLETED":
            payload = parse_tinyfish_result(run.get("result"))
            assert payload["source_url"].startswith("http")
            assert payload["page_title"]
            assert payload["evidence_snippet"]
            assert isinstance(payload["screenshot_useful"], bool)
            return

        if status in {"FAILED", "CANCELLED"}:
            pytest.fail(f"TinyFish run ended with {status}: {run.get('error')}")

        time.sleep(2)

    pytest.fail("TinyFish async smoke test timed out before completion")


def test_openai_reference_verifier_smoke_on_qmc_citation() -> None:
    require_live_tests()
    settings = load_settings()
    verifier = OpenAIReferenceVerifier(
        api_key=settings.openai_api_key,
        model=settings.openai_model_search,
    )

    result = verifier.verify(
        document_title="Quantum Monte Carlo for Exotic Option Pricing",
        claim_text=(
            "Quantum Amplitude Estimation reduces Monte Carlo sample complexity "
            "from O(1/epsilon^2) to O(1/epsilon)."
        ),
        claim_kind=ClaimKind.RESULT_CLAIM,
        card_summary="QAE gives a quadratic speedup over classical Monte Carlo.",
        evidence_spans=[
            "Classical Monte Carlo methods require O(1/epsilon^2) samples.",
            "Quantum Amplitude Estimation reduces this complexity to O(1/epsilon).",
        ],
        relation_type="cites",
        ref_label=None,
        raw_citation=(
            "Quantum Amplitude Amplification and Estimation. Brassard et al (2000). "
            "https://arxiv.org/abs/quant-ph/0005055"
        ),
        resolved_title="Quantum Amplitude Amplification and Estimation",
        resolved_url="https://arxiv.org/abs/quant-ph/0005055",
        resolved_doi=None,
    )

    assert result.exists_verdict is ReferenceExistenceVerdict.EXISTS
    assert result.support_verdict in {
        SupportVerdict.SUPPORTED,
        SupportVerdict.PARTIALLY_SUPPORTED,
    }
    assert result.reasoning_summary


def test_tinyfish_web_evidence_contract_on_qmc_citation() -> None:
    require_live_tests()
    settings = load_settings()
    acquirer = TinyFishWebEvidenceAcquirer(
        client=TinyFishClient(
            api_key=settings.tinyfish_api_key,
            base_url=settings.tinyfish_base_url,
        )
    )

    result = acquirer.acquire(
        document_title="Quantum Monte Carlo for Exotic Option Pricing",
        claim_text=(
            "Quantum Amplitude Estimation reduces Monte Carlo sample complexity "
            "from O(1/epsilon^2) to O(1/epsilon)."
        ),
        card_summary="QAE gives a quadratic speedup over classical Monte Carlo.",
        reference_label=None,
        raw_citation=(
            "Quantum Amplitude Amplification and Estimation. Brassard et al (2000). "
            "https://arxiv.org/abs/quant-ph/0005055"
        ),
        source_url="https://arxiv.org/abs/quant-ph/0005055",
    )

    assert result.status is TinyFishRunStatus.COMPLETED
    assert result.source_url and result.source_url.startswith("http")
    assert result.page_title
    assert result.evidence_snippet
    assert result.reasoning_summary
    assert result.screenshot_useful is not None
    if result.screenshot_data_uri is None:
        pytest.xfail(
            "TinyFish completed run did not include a base64 screenshot; "
            "structured evidence is available, but screenshot availability is not guaranteed yet.",
        )
    assert result.screenshot_data_uri.startswith("data:image/")
