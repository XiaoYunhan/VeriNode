from __future__ import annotations

from typing import Any

import httpx


class TinyFishClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 60,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout_seconds

    def run_async(
        self,
        *,
        url: str,
        goal: str,
        browser_profile: str = "lite",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/automation/run-async",
            json={
                "url": url,
                "goal": goal,
                "browser_profile": browser_profile,
            },
        )

    def run(
        self,
        *,
        url: str,
        goal: str,
        browser_profile: str = "lite",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/automation/run",
            json={
                "url": url,
                "goal": goal,
                "browser_profile": browser_profile,
            },
        )

    def get_runs_batch(self, *, run_ids: list[str]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/runs/batch",
            json={"run_ids": run_ids},
        )

    def get_run(
        self,
        *,
        run_id: str,
        screenshots: str = "none",
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/runs/{run_id}",
            params={"screenshots": screenshots},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
        ) as client:
            response = client.request(method, path, json=json, params=params)
            response.raise_for_status()
            return response.json()
