from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from verinode.database import Database
from verinode.extraction_types import (
    ExtractedClaimCard,
    ExtractedEvidenceSpan,
    ExtractedReference,
    ExtractionResult,
)
from verinode.main import create_app
from verinode.models import ClaimCard, ClaimKind, JobType, ReferenceExistenceVerdict, SupportVerdict, TinyFishRunStatus
from verinode.services.jobs import create_card_job
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
    def __init__(self, outcomes: list[ReferenceVerificationResult | Exception]) -> None:
        self._outcomes = outcomes
        self._lock = threading.Lock()

    def verify(self, **_: object) -> ReferenceVerificationResult:
        with self._lock:
            outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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
        enable_tinyfish=False,
    )


def sample_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        document_title="Sample Verification Paper",
        cards=[
            ExtractedClaimCard(
                claim_kind=ClaimKind.RESULT_CLAIM,
                claim_text="The model improves accuracy by 12%.",
                summary="Accuracy improves materially.",
                page_label="4",
                section_label="Results",
                evidence_spans=[
                    ExtractedEvidenceSpan(text="Accuracy improved from 71% to 83%.")
                ],
                references=[
                    ExtractedReference(
                        ref_label="[1]",
                        raw_citation="Smith et al. 2024",
                        resolved_title="Prior benchmark study",
                        resolved_url="https://example.com/benchmark",
                    )
                ],
            )
        ],
    )


def sample_extraction_result_without_references() -> ExtractionResult:
    return ExtractionResult(
        document_title="Uncited Verification Paper",
        cards=[
            ExtractedClaimCard(
                claim_kind=ClaimKind.FACTUAL_CLAIM,
                claim_text="The procedure converges in fewer than ten iterations.",
                summary="The procedure converges quickly.",
                evidence_spans=[
                    ExtractedEvidenceSpan(text="All runs converged in eight or fewer iterations.")
                ],
                references=[],
            )
        ],
    )


@contextmanager
def client_for(
    tmp_path: Path,
    *,
    extractor: ScriptedExtractor,
    verifier: ScriptedVerifier,
    acquirer: ScriptedWebEvidenceAcquirer | None = None,
) -> Iterator[TestClient]:
    settings = make_settings(tmp_path)
    if acquirer is not None:
        settings = settings.model_copy(update={"enable_tinyfish": True})
    with TestClient(
        create_app(
            settings,
            claim_extractor=extractor,
            reference_verifier=verifier,
            web_evidence_acquirer=acquirer,
        )
    ) as client:
        yield client


def wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    expected_status: str,
    timeout_seconds: float = 2,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        payload = response.json()
        if payload["status"] == expected_status:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {expected_status}")


def upload_and_extract_card(client: TestClient) -> str:
    document = client.post(
        "/api/documents",
        files={"file": ("paper.md", b"# Verification\n", "text/markdown")},
    ).json()
    job = client.post(f"/api/documents/{document['id']}/extract").json()
    wait_for_job(client, job["id"], expected_status="succeeded")
    cards = client.get(f"/api/documents/{document['id']}/cards").json()
    return cards[0]["id"]


def test_verify_job_persists_verdicts_and_claim_kind(tmp_path: Path) -> None:
    extractor = ScriptedExtractor(sample_extraction_result())
    verifier = ScriptedVerifier(
        [
            ReferenceVerificationResult(
                exists_verdict=ReferenceExistenceVerdict.EXISTS,
                support_verdict=SupportVerdict.SUPPORTED,
                reasoning_summary="The cited benchmark study reports the same improvement range.",
                source_url="https://example.com/benchmark",
            )
        ]
    )
    acquirer = ScriptedWebEvidenceAcquirer(
        [
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the source page.",
                run_id="verify-run-1",
                source_url="https://example.com/benchmark",
                page_title="Prior benchmark study",
                evidence_snippet="The benchmark reports a matching improvement range.",
                reasoning_summary="The source captures materially similar performance evidence.",
                screenshot_useful=True,
                screenshot_data_uri=ONE_PIXEL_PNG,
            )
        ]
    )

    with client_for(tmp_path, extractor=extractor, verifier=verifier, acquirer=acquirer) as client:
        card_id = upload_and_extract_card(client)

        verify_job = client.post(f"/api/cards/{card_id}/verify")
        assert verify_job.status_code == 202
        wait_for_job(client, verify_job.json()["id"], expected_status="succeeded")

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["claim_kind"] == "result_claim"
        assert card["stage"] == "web_evidence_acquired"
        assert len(card["verification_results"]) == 1
        assert len(card["tinyfish_runs"]) == 1
        assert card["verification_results"][0]["exists_verdict"] == "exists"
        assert card["verification_results"][0]["support_verdict"] == "supported"
        assert card["verification_results"][0]["reference"]["raw_citation"] == "Smith et al. 2024"


def test_failed_verify_job_is_retryable(tmp_path: Path) -> None:
    extractor = ScriptedExtractor(sample_extraction_result())
    verifier = ScriptedVerifier(
        [
            RuntimeError("verification failed"),
            ReferenceVerificationResult(
                exists_verdict=ReferenceExistenceVerdict.EXISTS,
                support_verdict=SupportVerdict.PARTIALLY_SUPPORTED,
                reasoning_summary="The source supports the direction but not the exact number.",
                source_url="https://example.com/benchmark",
            ),
        ]
    )

    with client_for(tmp_path, extractor=extractor, verifier=verifier) as client:
        card_id = upload_and_extract_card(client)

        first_job = client.post(f"/api/cards/{card_id}/verify").json()
        failed_state = wait_for_job(client, first_job["id"], expected_status="failed")
        assert failed_state["error_message"] == "verification failed"

        card_after_failure = client.get(f"/api/cards/{card_id}").json()
        assert card_after_failure["stage"] == "failed"

        retried = client.post(f"/api/jobs/{first_job['id']}/retry")
        assert retried.status_code == 202
        wait_for_job(client, first_job["id"], expected_status="succeeded")

        card_after_retry = client.get(f"/api/cards/{card_id}").json()
        assert card_after_retry["stage"] == "verified"
        assert card_after_retry["verification_results"][0]["support_verdict"] == "partially_supported"


def test_verify_job_supports_internet_lookup_when_card_has_no_declared_reference(
    tmp_path: Path,
) -> None:
    extractor = ScriptedExtractor(sample_extraction_result_without_references())
    verifier = ScriptedVerifier(
        [
            ReferenceVerificationResult(
                exists_verdict=ReferenceExistenceVerdict.EXISTS,
                support_verdict=SupportVerdict.SUPPORTED,
                reasoning_summary="A public methods page reports the same convergence behavior.",
                source_url="https://example.com/convergence",
            )
        ]
    )
    acquirer = ScriptedWebEvidenceAcquirer(
        [
            WebEvidenceAcquisition(
                status=TinyFishRunStatus.COMPLETED,
                goal="Inspect the source page.",
                run_id="lookup-run-1",
                source_url="https://example.com/convergence",
                page_title="Convergence Notes",
                evidence_snippet="The method converges in under ten iterations in the reported setup.",
                reasoning_summary="This page gives concrete browser-visible support for the uncited claim.",
                screenshot_useful=True,
                screenshot_data_uri=ONE_PIXEL_PNG,
            )
        ]
    )

    with client_for(tmp_path, extractor=extractor, verifier=verifier, acquirer=acquirer) as client:
        card_id = upload_and_extract_card(client)

        verify_job = client.post(f"/api/cards/{card_id}/verify")
        assert verify_job.status_code == 202
        wait_for_job(client, verify_job.json()["id"], expected_status="succeeded")

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["reference_mode"] == "internet_lookup"
        assert card["has_declared_reference"] is False
        assert card["stage"] == "web_evidence_acquired"
        assert card["references"][0]["relation_type"] == "internet_lookup"
        assert card["verification_results"][0]["source_url"] == "https://example.com/convergence"
        assert card["tinyfish_runs"][0]["status"] == "completed"


def test_startup_recovers_interrupted_verify_job_and_allows_rerun(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    extractor = ScriptedExtractor(sample_extraction_result())
    verifier = ScriptedVerifier(
        [
            ReferenceVerificationResult(
                exists_verdict=ReferenceExistenceVerdict.EXISTS,
                support_verdict=SupportVerdict.SUPPORTED,
                reasoning_summary="The cited benchmark study reports the same improvement range.",
                source_url="https://example.com/benchmark",
            )
        ]
    )

    with TestClient(
        create_app(
            settings,
            claim_extractor=extractor,
            reference_verifier=verifier,
        )
    ) as client:
        card_id = upload_and_extract_card(client)

    database = Database(settings.database_url)
    session = database.session()
    try:
        card = session.get(ClaimCard, card_id)
        assert card is not None
        job = create_card_job(
            session,
            claim_card=card,
            job_type=JobType.VERIFY_CARD,
        )
        job_id = job.id
    finally:
        session.close()

    extractor = ScriptedExtractor(sample_extraction_result())
    verifier = ScriptedVerifier(
        [
            ReferenceVerificationResult(
                exists_verdict=ReferenceExistenceVerdict.EXISTS,
                support_verdict=SupportVerdict.SUPPORTED,
                reasoning_summary="The cited benchmark study reports the same improvement range.",
                source_url="https://example.com/benchmark",
            )
        ]
    )
    with TestClient(
        create_app(
            settings,
            claim_extractor=extractor,
            reference_verifier=verifier,
        )
    ) as client:
        recovered_job = client.get(f"/api/jobs/{job_id}")
        assert recovered_job.status_code == 200
        assert recovered_job.json()["status"] == "failed"
        assert "interrupted" in recovered_job.json()["error_message"].lower()

        card_after_recovery = client.get(f"/api/cards/{card_id}").json()
        assert card_after_recovery["stage"] == "failed"

        rerun = client.post(f"/api/cards/{card_id}/verify")
        assert rerun.status_code == 202
        wait_for_job(client, rerun.json()["id"], expected_status="succeeded")
