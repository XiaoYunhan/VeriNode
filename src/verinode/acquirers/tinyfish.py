from __future__ import annotations

import json
import time
from typing import Any

from verinode.clients.tinyfish import TinyFishClient
from verinode.models import TinyFishRunStatus
from verinode.services.references import build_evidence_target_url
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
        attempts = [
            (source_url, "lite"),
        ]
        fallback_url = build_evidence_target_url(source_url, raw_citation=raw_citation)
        if fallback_url and fallback_url != source_url:
            attempts.append((fallback_url, "stealth"))

        last_acquisition: WebEvidenceAcquisition | None = None
        for attempt_url, browser_profile in attempts:
            acquisition = self._run_once(
                url=attempt_url,
                goal=goal,
                browser_profile=browser_profile,
            )
            if _has_usable_screenshot(acquisition):
                return acquisition
            last_acquisition = acquisition

        if last_acquisition is not None:
            return last_acquisition
        return WebEvidenceAcquisition(
            status=TinyFishRunStatus.FAILED,
            goal=goal,
            run_id=None,
            source_url=source_url,
            error_message="tinyfish_web_evidence_failed",
        )

    def _run_once(
        self,
        *,
        url: str,
        goal: str,
        browser_profile: str,
    ) -> WebEvidenceAcquisition:
        started = self._client.run_async(url=url, goal=goal, browser_profile=browser_profile)
        run_id = started.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            return WebEvidenceAcquisition(
                status=TinyFishRunStatus.FAILED,
                goal=goal,
                run_id=None,
                source_url=url,
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
                source_url=url,
                error_message=_extract_error_message(error),
            )

        result_payload = _parse_result(run.get("result"))
        detail = self._client.get_run(run_id=run_id, screenshots="base64") if run_id else run
        screenshot_data_uri = _extract_screenshot_data_uri(detail)

        return WebEvidenceAcquisition(
            status=status,
            goal=goal,
            run_id=run_id,
            source_url=result_payload.get("source_url") or url,
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
            run = self._client.get_run(run_id=run_id, screenshots="none")
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
You should navigate beyond the landing page when needed to reach the actual full-text evidence view.
Return JSON only with exactly these keys:
source_url, page_title, evidence_snippet, reasoning_summary, screenshot_useful

Rules:
- Start from the provided URL, but do not stop at an abstract or citation landing page if a fuller evidence view is available
- If the page is an arXiv abstract page, click the PDF view before deciding whether the claim is supported
- If the page is a publisher or index landing page, open the HTML full text, PDF, appendix, or figure view that best supports the claim
- Scroll or zoom until the supporting sentence, equation, table, or figure is visible on screen
- The screenshot should focus on the evidence region, not just the landing page chrome
- source_url must be the final page you actually used for the screenshot
- evidence_snippet should be a short direct quote or a tight paraphrase under 80 words
- reasoning_summary should explain either why the captured evidence supports the claim or why full-text capture was blocked
- screenshot_useful must be true or false
- If you cannot reach a supporting full-text view, set screenshot_useful to false and explain the blocker in reasoning_summary
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


def _extract_screenshot_data_uri(value: Any) -> str | None:
    matches: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node.startswith("data:image/"):
                matches.append(node)
            return
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return matches[-1] if matches else None


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


def _has_usable_screenshot(acquisition: WebEvidenceAcquisition) -> bool:
    if acquisition.status is not TinyFishRunStatus.COMPLETED:
        return False
    if acquisition.screenshot_useful is False:
        return False
    return bool(acquisition.screenshot_data_uri)
