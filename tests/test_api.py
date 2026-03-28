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
from verinode.settings import Settings


class ScriptedExtractor:
    def __init__(
        self,
        outcomes: list[ExtractionResult | Exception],
        *,
        started_event: threading.Event | None = None,
        release_event: threading.Event | None = None,
    ) -> None:
        self._outcomes = outcomes
        self._started_event = started_event
        self._release_event = release_event
        self._lock = threading.Lock()

    def extract(self, **_: object) -> ExtractionResult:
        if self._started_event is not None:
            self._started_event.set()
        if self._release_event is not None:
            self._release_event.wait(timeout=2)

        with self._lock:
            if not self._outcomes:
                raise RuntimeError("no scripted outcome left")
            outcome = self._outcomes.pop(0)

        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def sample_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        document_title="Sample Paper",
        cards=[
            ExtractedClaimCard(
                claim_text="The treatment reduced error rates by 12%.",
                summary="Treatment improves accuracy.",
                page_label="2",
                section_label="Results",
                evidence_spans=[
                    ExtractedEvidenceSpan(
                        text="Error rates dropped from 31% to 19%.",
                        page_label="2",
                        start_anchor="paragraph-4",
                        end_anchor="paragraph-4",
                    )
                ],
                references=[
                    ExtractedReference(
                        ref_label="[1]",
                        raw_citation="Smith et al. 2024",
                        resolved_title="Prior treatment study",
                        resolved_url="https://example.com/ref-1",
                    )
                ],
            )
        ],
    )


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


@contextmanager
def client_for(
    tmp_path: Path,
    extractor: ScriptedExtractor,
) -> Iterator[tuple[TestClient, Settings]]:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, claim_extractor=extractor)) as client:
        yield client, settings


def upload_markdown_document(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/documents",
        files={"file": ("paper.md", b"# Sample claim\n", "text/markdown")},
    )
    assert response.status_code == 201
    return response.json()


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


def test_upload_document_persists_metadata_and_file(tmp_path: Path) -> None:
    extractor = ScriptedExtractor([sample_extraction_result()])
    with client_for(tmp_path, extractor) as (client, settings):
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        response = client.post(
            "/api/documents",
            files={"file": ("paper.md", b"# Sample claim\n", "text/markdown")},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["filename"] == "paper.md"
        assert payload["file_type"] == "markdown"
        assert payload["status"] == "uploaded"
        assert (settings.app_data_dir / payload["storage_path"]).read_bytes() == b"# Sample claim\n"

        listed_documents = client.get("/api/documents").json()
        assert len(listed_documents) == 1
        assert listed_documents[0]["id"] == payload["id"]


def test_extract_job_persists_cards_evidence_and_references(tmp_path: Path) -> None:
    extractor = ScriptedExtractor([sample_extraction_result()])
    with client_for(tmp_path, extractor) as (client, _settings):
        document = upload_markdown_document(client)

        job = client.post(f"/api/documents/{document['id']}/extract").json()
        finished_job = wait_for_job(client, job["id"], expected_status="succeeded")
        assert finished_job["job_type"] == "extract_claims"

        document_after = client.get(f"/api/documents/{document['id']}").json()
        assert document_after["status"] == "ready"
        assert document_after["title"] == "Sample Paper"

        cards = client.get(f"/api/documents/{document['id']}/cards").json()
        assert len(cards) == 1
        assert cards[0]["stage"] == "extracted"

        card = client.get(f"/api/cards/{cards[0]['id']}").json()
        assert card["summary"] == "Treatment improves accuracy."
        assert card["evidence_spans"][0]["text"] == "Error rates dropped from 31% to 19%."
        assert card["references"][0]["relation_type"] == "cites"
        assert card["references"][0]["reference"]["raw_citation"] == "Smith et al. 2024"


def test_extract_endpoint_rejects_duplicate_active_jobs(tmp_path: Path) -> None:
    started_event = threading.Event()
    release_event = threading.Event()
    extractor = ScriptedExtractor(
        [sample_extraction_result()],
        started_event=started_event,
        release_event=release_event,
    )

    with client_for(tmp_path, extractor) as (client, _settings):
        document = upload_markdown_document(client)

        first_extract = client.post(f"/api/documents/{document['id']}/extract")
        assert first_extract.status_code == 202
        assert started_event.wait(timeout=1)

        second_extract = client.post(f"/api/documents/{document['id']}/extract")
        assert second_extract.status_code == 409
        assert second_extract.json()["detail"]["code"] == "extract_job_exists"

        release_event.set()
        wait_for_job(client, first_extract.json()["id"], expected_status="succeeded")


def test_failed_extract_job_is_retryable(tmp_path: Path) -> None:
    extractor = ScriptedExtractor(
        [RuntimeError("extract failed"), sample_extraction_result()]
    )

    with client_for(tmp_path, extractor) as (client, _settings):
        document = upload_markdown_document(client)

        failed_job = client.post(f"/api/documents/{document['id']}/extract").json()
        failed_state = wait_for_job(client, failed_job["id"], expected_status="failed")
        assert failed_state["error_message"] == "extract failed"

        document_after_failure = client.get(f"/api/documents/{document['id']}").json()
        assert document_after_failure["status"] == "failed"

        retried_job = client.post(f"/api/jobs/{failed_job['id']}/retry")
        assert retried_job.status_code == 202
        assert retried_job.json()["status"] == "queued"

        succeeded_state = wait_for_job(
            client,
            failed_job["id"],
            expected_status="succeeded",
        )
        assert succeeded_state["error_message"] is None

        document_after_retry = client.get(f"/api/documents/{document['id']}").json()
        assert document_after_retry["status"] == "ready"
