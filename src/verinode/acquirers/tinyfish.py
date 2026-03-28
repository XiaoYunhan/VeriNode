from __future__ import annotations

import json
import time
from typing import Any

from verinode.clients.tinyfish import TinyFishClient
from verinode.models import TinyFishRunStatus
from verinode.web_evidence_types import WebEvidenceAcquisition


class TinyFishWebEvidenceAcquirer:
    def __init__(
        self,
        *,
        client: TinyFishClient,
        poll_interval_seconds: float = 2,
        max_wait_seconds: float = 300,
    ) -> None:
        self._client = client
        self._poll_interval_seconds = poll_interval_seconds
        self._max_wait_seconds = max_wait_seconds

    def acquire(
        self,
        *,
        document_title: str | None,
        claim_text: str | None,
        card_summary: str | None,
        reference_label: str | None,
        raw_citation: str,
        source_url: str,
    ) -> WebEvidenceAcquisition:
        goal = self._build_goal(
            document_title=document_title,
            claim_text=claim_text,
            card_summary=card_summary,
            reference_label=reference_label,
            raw_citation=raw_citation,
        )
        started = self._client.run_async(url=source_url, goal=goal, browser_profile="lite")
        run_id = started.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            return WebEvidenceAcquisition(
                status=TinyFishRunStatus.FAILED,
                goal=goal,
                run_id=None,
                source_url=source_url,
                error_message="tinyfish_missing_run_id",
            )

        run = self._wait_for_terminal_run(run_id=run_id)
        status = _parse_status(run.get("status"))

        if status is not TinyFishRunStatus.COMPLETED:
            error = run.get("error") or {}
            return WebEvidenceAcquisition(
                status=status,
                goal=goal,
                run_id=run_id,
                source_url=source_url,
                error_message=_extract_error_message(error),
            )

        result_payload = _parse_result(run.get("result"))
        detail = self._client.get_run(run_id=run_id, screenshots="base64") if run_id else run
        screenshot_data_uri = _extract_screenshot_data_uri(detail.get("steps") or [])

        return WebEvidenceAcquisition(
            status=status,
            goal=goal,
            run_id=run_id,
            source_url=result_payload.get("source_url") or source_url,
            page_title=_coerce_string(result_payload.get("page_title")),
            evidence_snippet=_coerce_string(result_payload.get("evidence_snippet")),
            reasoning_summary=_coerce_string(result_payload.get("reasoning_summary")),
            screenshot_useful=_coerce_bool(result_payload.get("screenshot_useful")),
            screenshot_data_uri=screenshot_data_uri,
        )

    def _wait_for_terminal_run(self, *, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._max_wait_seconds
        last_run: dict[str, Any] | None = None

        while time.monotonic() < deadline:
            run = self._client.get_run(run_id=run_id, screenshots="base64")
            last_run = run
            status = _parse_status(run.get("status"))
            if status in {
                TinyFishRunStatus.COMPLETED,
                TinyFishRunStatus.FAILED,
                TinyFishRunStatus.CANCELLED,
            }:
                return run
            time.sleep(self._poll_interval_seconds)

        return {
            "run_id": run_id,
            "status": TinyFishRunStatus.FAILED.value,
            "error": {"message": "tinyfish_web_evidence_timeout"},
            "result": last_run.get("result") if isinstance(last_run, dict) else None,
            "steps": last_run.get("steps") if isinstance(last_run, dict) else [],
        }

    def _build_goal(
        self,
        *,
        document_title: str | None,
        claim_text: str | None,
        card_summary: str | None,
        reference_label: str | None,
        raw_citation: str,
    ) -> str:
        return f"""
Inspect this reference page for evidence relevant to the paper claim below.
Return JSON only with exactly these keys:
source_url, page_title, evidence_snippet, reasoning_summary, screenshot_useful

Rules:
- source_url must be the page you actually used
- evidence_snippet should be a short direct quote or a tight paraphrase under 80 words
- reasoning_summary should explain why this page is useful for verification in 1 sentence
- screenshot_useful must be true or false
- do not include markdown fences or any extra keys

Document title: {document_title or "unknown"}
Claim text: {claim_text or "none"}
Card summary: {card_summary or "none"}
Reference label: {reference_label or "none"}
Raw citation: {raw_citation}
""".strip()


def _parse_status(value: Any) -> TinyFishRunStatus:
    normalized = str(value or "").strip().lower()
    if normalized == "pending":
        return TinyFishRunStatus.PENDING
    if normalized == "running":
        return TinyFishRunStatus.RUNNING
    if normalized == "completed":
        return TinyFishRunStatus.COMPLETED
    if normalized == "cancelled":
        return TinyFishRunStatus.CANCELLED
    return TinyFishRunStatus.FAILED


def _parse_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"reasoning_summary": value}
        return parsed if isinstance(parsed, dict) else {"reasoning_summary": value}
    return {}


def _extract_screenshot_data_uri(steps: list[dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        screenshot = step.get("screenshot")
        if isinstance(screenshot, str) and screenshot.startswith("data:image/"):
            return screenshot
    return None


def _extract_error_message(error: Any) -> str:
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message
    if isinstance(error, str) and error.strip():
        return error
    return "tinyfish_web_evidence_failed"


def _coerce_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None
