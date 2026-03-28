from __future__ import annotations

from verinode.acquirers.tinyfish import TinyFishWebEvidenceAcquirer
from verinode.models import TinyFishRunStatus

ONE_PIXEL_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sX8N7sAAAAASUVORK5CYII="
)


class ScriptedTinyFishClient:
    def __init__(self) -> None:
        self.run_calls: list[tuple[str, str]] = []
        self.get_run_calls: list[tuple[str, str]] = []
        self._runs = {
            "run-1": {
                "run_id": "run-1",
                "status": "COMPLETED",
                "result": {
                    "source_url": "https://arxiv.org/abs/quant-ph/0005055",
                    "page_title": "Quantum Amplitude Amplification and Estimation",
                    "evidence_snippet": "The abstract page was visited.",
                    "reasoning_summary": "No screenshot artifact was returned on the first attempt.",
                    "screenshot_useful": False,
                },
                "steps": [],
            },
            "run-2": {
                "run_id": "run-2",
                "status": "COMPLETED",
                "result": {
                    "source_url": "https://arxiv.org/pdf/quant-ph/0005055.pdf",
                    "page_title": "Quantum Amplitude Amplification and Estimation",
                    "evidence_snippet": "Amplitude estimation achieves a quadratic speedup.",
                    "reasoning_summary": "The PDF view exposed the supporting statement on screen.",
                    "screenshot_useful": True,
                },
                "steps": [
                    {
                        "id": "step-2",
                        "status": "COMPLETED",
                        "action": "Open the PDF view.",
                        "screenshot": ONE_PIXEL_PNG,
                    }
                ],
            },
        }

    def run_async(self, *, url: str, goal: str, browser_profile: str = "lite") -> dict[str, str]:
        self.run_calls.append((url, browser_profile))
        run_id = f"run-{len(self.run_calls)}"
        return {"run_id": run_id}

    def get_run(self, *, run_id: str, screenshots: str = "none") -> dict[str, object]:
        self.get_run_calls.append((run_id, screenshots))
        return self._runs[run_id]


def test_tinyfish_acquirer_retries_arxiv_reference_on_pdf_target() -> None:
    client = ScriptedTinyFishClient()
    acquirer = TinyFishWebEvidenceAcquirer(client=client, poll_interval_seconds=0, max_wait_seconds=1)

    result = acquirer.acquire(
        document_title="Quantum Monte Carlo for Exotic Option Pricing",
        claim_text="Quantum Amplitude Estimation reduces sample complexity to O(1/epsilon).",
        card_summary="QAE gives a quadratic speedup over classical Monte Carlo.",
        reference_label=None,
        raw_citation=(
            "Quantum Amplitude Amplification and Estimation. Brassard et al (2000). "
            "https://arxiv.org/abs/quant-ph/0005055"
        ),
        source_url="https://arxiv.org/abs/quant-ph/0005055",
    )

    assert client.run_calls == [
        ("https://arxiv.org/abs/quant-ph/0005055", "lite"),
        ("https://arxiv.org/pdf/quant-ph/0005055.pdf", "stealth"),
    ]
    assert client.get_run_calls == [
        ("run-1", "none"),
        ("run-1", "base64"),
        ("run-2", "none"),
        ("run-2", "base64"),
    ]
    assert result.status is TinyFishRunStatus.COMPLETED
    assert result.source_url == "https://arxiv.org/pdf/quant-ph/0005055.pdf"
    assert result.screenshot_data_uri == ONE_PIXEL_PNG


def test_tinyfish_acquirer_does_not_repeat_same_url_when_no_better_target_exists() -> None:
    client = ScriptedTinyFishClient()
    client._runs = {
        "run-1": {
            "run_id": "run-1",
            "status": "COMPLETED",
            "result": {
                "source_url": "https://example.com/reference",
                "page_title": "Reference Page",
                "evidence_snippet": "The page was visited.",
                "reasoning_summary": "No screenshot was returned.",
                "screenshot_useful": False,
            },
            "steps": [],
        },
    }
    acquirer = TinyFishWebEvidenceAcquirer(client=client, poll_interval_seconds=0, max_wait_seconds=1)

    result = acquirer.acquire(
        document_title="Example Paper",
        claim_text="Example claim.",
        card_summary="Example summary.",
        reference_label=None,
        raw_citation="Example citation https://example.com/reference",
        source_url="https://example.com/reference",
    )

    assert client.run_calls == [
        ("https://example.com/reference", "lite"),
    ]
    assert result.source_url == "https://example.com/reference"
