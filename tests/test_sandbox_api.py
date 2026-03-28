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
    ExtractionResult,
)
from verinode.main import create_app
from verinode.models import CardType, ClaimKind, SandboxRunStatus
from verinode.sandbox_types import SandboxExecutionResult
from verinode.settings import Settings


class ScriptedExtractor:
    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    def extract(self, **_: object) -> ExtractionResult:
        return self._result


class ScriptedSandboxExecutor:
    def __init__(self, outcomes: list[SandboxExecutionResult | Exception]) -> None:
        self._outcomes = outcomes
        self._lock = threading.Lock()

    def execute(self, **_: object) -> SandboxExecutionResult:
        with self._lock:
            outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class BlockingSandboxExecutor:
    def __init__(self, release_event: threading.Event) -> None:
        self.release_event = release_event
        self.started_event = threading.Event()
        self._lock = threading.Lock()
        self._calls = 0

    def execute(self, **_: object) -> SandboxExecutionResult:
        with self._lock:
            self._calls += 1
            call_number = self._calls

        if call_number == 1:
            self.started_event.set()
            assert self.release_event.wait(timeout=2)

        return SandboxExecutionResult(
            status=SandboxRunStatus.COMPLETED,
            summary=f"Sandbox run {call_number} completed.",
            full_process=f"## Summary\nSandbox run {call_number} completed.",
        )


def make_settings(tmp_path: Path, *, max_concurrent_jobs: int = 2) -> Settings:
    return Settings(
        openai_api_key="test-openai-key",
        openai_model_main="gpt-5.4",
        openai_model_search="gpt-5.4-mini",
        openai_model_sandbox="gpt-5.4",
        tinyfish_api_key="test-tinyfish-key",
        tinyfish_base_url="https://tinyfish.invalid",
        app_data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        max_concurrent_jobs=max_concurrent_jobs,
        enable_tinyfish=False,
        enable_code_sandbox=True,
    )


def sample_code_extraction() -> ExtractionResult:
    return ExtractionResult(
        document_title="Sandbox Paper",
        cards=[
            ExtractedClaimCard(
                card_type=CardType.MATH,
                claim_kind=ClaimKind.CODE_MATH_ARTIFACT,
                claim_text="The recurrence solves to n log n.",
                summary="The recurrence has n log n complexity.",
                evidence_spans=[
                    ExtractedEvidenceSpan(text="T(n) = 2T(n/2) + n.")
                ],
            )
        ],
    )


def sample_two_card_extraction() -> ExtractionResult:
    return ExtractionResult(
        document_title="Sandbox Paper",
        cards=[
            ExtractedClaimCard(
                card_type=CardType.MATH,
                claim_kind=ClaimKind.CODE_MATH_ARTIFACT,
                claim_text="The recurrence solves to n log n.",
                summary="The recurrence has n log n complexity.",
                evidence_spans=[
                    ExtractedEvidenceSpan(text="T(n) = 2T(n/2) + n.")
                ],
            ),
            ExtractedClaimCard(
                card_type=CardType.CODE,
                claim_kind=ClaimKind.CODE_MATH_ARTIFACT,
                claim_text="The sample implementation returns the sorted list.",
                summary="The implementation sorts the input list.",
                evidence_spans=[
                    ExtractedEvidenceSpan(text="def sort_values(values): return sorted(values)")
                ],
            ),
        ],
    )


@contextmanager
def client_for(
    tmp_path: Path,
    *,
    sandbox_executor: ScriptedSandboxExecutor,
    extraction_result: ExtractionResult | None = None,
    max_concurrent_jobs: int = 2,
) -> Iterator[tuple[TestClient, Path]]:
    settings = make_settings(tmp_path, max_concurrent_jobs=max_concurrent_jobs)
    with TestClient(
        create_app(
            settings,
            claim_extractor=ScriptedExtractor(extraction_result or sample_code_extraction()),
            sandbox_executor=sandbox_executor,
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


def upload_and_extract_card(client: TestClient) -> str:
    document = client.post(
        "/api/documents",
        files={"file": ("sandbox.md", b"# Sandbox\n", "text/markdown")},
    ).json()
    extract_job = client.post(f"/api/documents/{document['id']}/extract").json()
    wait_for_job(client, extract_job["id"], expected_status="succeeded")
    return client.get(f"/api/documents/{document['id']}/cards").json()[0]["id"]


def upload_and_extract_cards(client: TestClient) -> list[str]:
    document = client.post(
        "/api/documents",
        files={"file": ("sandbox.md", b"# Sandbox\n", "text/markdown")},
    ).json()
    extract_job = client.post(f"/api/documents/{document['id']}/extract").json()
    wait_for_job(client, extract_job["id"], expected_status="succeeded")
    return [card["id"] for card in client.get(f"/api/documents/{document['id']}/cards").json()]


def test_sandbox_job_persists_process_artifact(tmp_path: Path) -> None:
    executor = ScriptedSandboxExecutor(
        [
            SandboxExecutionResult(
                status=SandboxRunStatus.COMPLETED,
                summary="The recurrence solves to n log n by the Master theorem.",
                full_process="## Summary\nThe recurrence solves to n log n.\n\n## Process\nApply the Master theorem.",
            )
        ]
    )

    with client_for(tmp_path, sandbox_executor=executor) as (client, data_dir):
        card_id = upload_and_extract_card(client)

        verify_response = client.post(f"/api/cards/{card_id}/verify")
        assert verify_response.status_code == 409
        assert verify_response.json()["detail"]["code"] == "code_math_requires_sandbox"

        job = client.post(f"/api/cards/{card_id}/sandbox")
        assert job.status_code == 202
        wait_for_job(client, job.json()["id"], expected_status="succeeded")

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["stage"] == "sandboxed"
        assert len(card["sandbox_runs"]) == 1
        assert card["sandbox_runs"][0]["status"] == "completed"
        assert card["sandbox_runs"][0]["artifact_path"].startswith("artifacts/sandbox/")
        assert any(span["source_kind"] == "sandbox" for span in card["evidence_spans"])
        artifact_path = data_dir / card["sandbox_runs"][0]["artifact_path"]
        assert artifact_path.exists()
        artifact_html = artifact_path.read_text(encoding="utf-8")
        assert "Rendered" in artifact_html
        assert "Markdown" in artifact_html
        assert "<h2>Summary</h2>" in artifact_html


def test_failed_sandbox_job_is_retryable(tmp_path: Path) -> None:
    executor = ScriptedSandboxExecutor(
        [
            RuntimeError("sandbox failed"),
            SandboxExecutionResult(
                status=SandboxRunStatus.COMPLETED,
                summary="Retry succeeded with n log n complexity.",
                full_process="## Summary\nRetry succeeded.\n\n## Process\nSecond run completed.",
            ),
        ]
    )

    with client_for(tmp_path, sandbox_executor=executor) as (client, _data_dir):
        card_id = upload_and_extract_card(client)

        first_job = client.post(f"/api/cards/{card_id}/sandbox").json()
        failed = wait_for_job(client, first_job["id"], expected_status="failed")
        assert failed["error_message"] == "sandbox failed"

        retried = client.post(f"/api/jobs/{first_job['id']}/retry")
        assert retried.status_code == 202
        wait_for_job(client, first_job["id"], expected_status="succeeded")

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["stage"] == "sandboxed"
        assert card["sandbox_runs"][-1]["status"] == "completed"


def test_can_enqueue_second_sandbox_job_while_first_is_running(tmp_path: Path) -> None:
    release_event = threading.Event()
    executor = BlockingSandboxExecutor(release_event)

    with client_for(
        tmp_path,
        sandbox_executor=executor,
        extraction_result=sample_two_card_extraction(),
        max_concurrent_jobs=1,
    ) as (client, _data_dir):
        first_card_id, second_card_id = upload_and_extract_cards(client)

        first_job = client.post(f"/api/cards/{first_card_id}/sandbox")
        assert first_job.status_code == 202
        assert executor.started_event.wait(timeout=2)

        second_job = client.post(f"/api/cards/{second_card_id}/sandbox")
        assert second_job.status_code == 202

        release_event.set()
        wait_for_job(client, first_job.json()["id"], expected_status="succeeded")
        wait_for_job(client, second_job.json()["id"], expected_status="succeeded")
