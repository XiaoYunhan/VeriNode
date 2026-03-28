from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from verinode.extraction_types import (
    ExtractedClaimCard,
    ExtractedEvidenceSpan,
    ExtractedReference,
    ExtractionResult,
)
from verinode.main import create_app
from verinode.models import ClaimKind, TinyFishRunStatus
from verinode.settings import Settings
from verinode.verification_types import ReferenceVerificationResult
from verinode.web_evidence_types import WebEvidenceAcquisition


ONE_PIXEL_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sX8N7sAAAAASUVORK5CYII="
)


class ScriptedExtractor:
    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    def extract(self, **_: object) -> ExtractionResult:
        return self._result


class ScriptedVerifier:
    def __init__(self, result: ReferenceVerificationResult) -> None:
        self._result = result

    def verify(self, **_: object) -> ReferenceVerificationResult:
        return self._result


class ScriptedWebEvidenceAcquirer:
    def __init__(self, outcomes: list[WebEvidenceAcquisition | Exception]) -> None:
        self._outcomes = outcomes
        self._lock = threading.Lock()

    def acquire(self, **_: object) -> WebEvidenceAcquisition:
        with self._lock:
            outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key="test-openai-key",
        openai_model_main="gpt-5.4",
        openai_model_search="gpt-5.4-mini",
        openai_model_sandbox="gpt-5.4",
        tinyfish_api_key="test-tinyfish-key",
        tinyfish_base_url="https://tinyfish.invalid",
        app_data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )


def sample_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        document_title="Sample TinyFish Paper",
        cards=[
            ExtractedClaimCard(
                claim_kind=ClaimKind.RESULT_CLAIM,
                claim_text="QAE reduces sample complexity to O(1/epsilon).",
                summary="QAE yields a quadratic speedup.",
                evidence_spans=[ExtractedEvidenceSpan(text="QAE reduces complexity to O(1/epsilon).")],
                references=[
                    ExtractedReference(
                        ref_label="[1]",
                        raw_citation="Brassard et al. 2000. https://arxiv.org/abs/quant-ph/0005055",
                        resolved_title="Quantum Amplitude Amplification and Estimation",
                        resolved_url="https://arxiv.org/abs/quant-ph/0005055",
                    )
                ],
            )
        ],
    )


@contextmanager
def client_for(
    tmp_path: Path,
    *,
    acquirer: ScriptedWebEvidenceAcquirer,
) -> Iterator[tuple[TestClient, Path]]:
    settings = make_settings(tmp_path)
    with TestClient(
        create_app(
            settings,
            claim_extractor=ScriptedExtractor(sample_extraction_result()),
            reference_verifier=ScriptedVerifier(
                ReferenceVerificationResult(
                    exists_verdict="exists",
                    support_verdict="supported",
                    reasoning_summary="The citation supports the claim.",
                    source_url="https://arxiv.org/abs/quant-ph/0005055",
                )
            ),
            web_evidence_acquirer=acquirer,
        )
    ) as client:
        yield client, settings.app_data_dir


def wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    expected_status: str,
    timeout_seconds: float = 2,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] == expected_status:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {expected_status}")


def upload_extract_and_verify(client: TestClient) -> str:
    document = client.post(
        "/api/documents",
        files={"file": ("paper.md", b"# TinyFish\n", "text/markdown")},
    ).json()
    extract_job = client.post(f"/api/documents/{document['id']}/extract").json()
    wait_for_job(client, extract_job["id"], expected_status="succeeded")
    card_id = client.get(f"/api/documents/{document['id']}/cards").json()[0]["id"]
    verify_job = client.post(f"/api/cards/{card_id}/verify").json()
    wait_for_job(client, verify_job["id"], expected_status="succeeded")
    return card_id


def test_web_evidence_job_persists_tinyfish_run_and_artifact(tmp_path: Path) -> None:
    acquirer = ScriptedWebEvidenceAcquirer(
        [
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the citation page during verification.",
                run_id="run-verify",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                page_title="Quantum Amplitude Amplification and Estimation",
                evidence_snippet="The paper presents amplitude estimation with quadratic speedup.",
                reasoning_summary="The verification step captured the canonical source page.",
                screenshot_useful=True,
                screenshot_data_uri=ONE_PIXEL_PNG,
            ),
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the citation page.",
                run_id="run-123",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                page_title="Quantum Amplitude Amplification and Estimation",
                evidence_snippet="The paper presents amplitude estimation with quadratic speedup.",
                reasoning_summary="This page directly describes the algorithm cited by the claim.",
                screenshot_useful=True,
                screenshot_data_uri=ONE_PIXEL_PNG,
            )
        ]
    )

    with client_for(tmp_path, acquirer=acquirer) as (client, data_dir):
        card_id = upload_extract_and_verify(client)

        job = client.post(f"/api/cards/{card_id}/web-evidence")
        assert job.status_code == 202
        wait_for_job(client, job.json()["id"], expected_status="succeeded")

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["stage"] == "web_evidence_acquired"
        assert len(card["tinyfish_runs"]) >= 2
        assert card["tinyfish_runs"][-1]["status"] == "completed"
        assert card["tinyfish_runs"][-1]["artifact_path"].startswith("artifacts/tinyfish/")
        assert any(span["source_kind"] == "tinyfish" for span in card["evidence_spans"])
        assert (data_dir / card["tinyfish_runs"][-1]["artifact_path"]).exists()


def test_failed_web_evidence_job_is_retryable(tmp_path: Path) -> None:
    acquirer = ScriptedWebEvidenceAcquirer(
        [
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the citation page during verification.",
                run_id="run-verify",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                evidence_snippet="Initial verification captured baseline evidence.",
                reasoning_summary="Verification succeeded.",
                screenshot_useful=False,
            ),
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.FAILED,
                goal="Inspect the citation page.",
                run_id="run-failed",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                error_message="tinyfish failed",
            ),
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the citation page.",
                run_id="run-ok",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                evidence_snippet="Recovered evidence after retry.",
                reasoning_summary="Retry succeeded.",
                screenshot_useful=True,
                screenshot_data_uri=ONE_PIXEL_PNG,
            ),
        ]
    )

    with client_for(tmp_path, acquirer=acquirer) as (client, _data_dir):
        card_id = upload_extract_and_verify(client)

        first_job = client.post(f"/api/cards/{card_id}/web-evidence").json()
        failed = wait_for_job(client, first_job["id"], expected_status="failed")
        assert failed["error_message"] == "tinyfish failed"

        retried = client.post(f"/api/jobs/{first_job['id']}/retry")
        assert retried.status_code == 202
        wait_for_job(client, first_job["id"], expected_status="succeeded")

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["stage"] == "web_evidence_acquired"
        assert card["tinyfish_runs"][-1]["status"] == "completed"


def test_completed_web_evidence_without_screenshot_is_blocked(tmp_path: Path) -> None:
    acquirer = ScriptedWebEvidenceAcquirer(
        [
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the citation page during verification.",
                run_id="run-verify",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                evidence_snippet="Verification found the citation page.",
                reasoning_summary="The verification step visited the source page.",
                screenshot_useful=False,
            ),
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the citation page.",
                run_id="run-no-screenshot",
                source_url="https://arxiv.org/abs/quant-ph/0005055",
                evidence_snippet="The page mentions amplitude estimation.",
                reasoning_summary="TinyFish reached the page but no screenshot artifact was returned.",
                screenshot_useful=False,
            ),
        ]
    )

    with client_for(tmp_path, acquirer=acquirer) as (client, _data_dir):
        card_id = upload_extract_and_verify(client)

        job = client.post(f"/api/cards/{card_id}/web-evidence").json()
        failed = wait_for_job(client, job["id"], expected_status="failed")
        assert "screenshot" in failed["error_message"].lower()

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["stage"] == "failed"
        assert card["tinyfish_runs"][-1]["status"] == "failed"
        assert "screenshot" in card["tinyfish_runs"][-1]["result_summary"].lower()
