from __future__ import annotations

from html import escape
import re
from typing import Any

from openai import OpenAI

from verinode.models import CardType, SandboxRunStatus
from verinode.prompts import SANDBOX_EXECUTION_SYSTEM_PROMPT
from verinode.sandbox_types import SandboxExecutionResult


class OpenAISandboxExecutor:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def execute(
        self,
        *,
        document_title: str | None,
        card_type: CardType,
        claim_text: str | None,
        card_summary: str | None,
        evidence_spans: list[str],
    ) -> SandboxExecutionResult:
        response = self._client.responses.create(
            model=self._model,
            tools=[
                {
                    "type": "code_interpreter",
                    "container": {"type": "auto"},
                }
            ],
            tool_choice="required",
            instructions=SANDBOX_EXECUTION_SYSTEM_PROMPT,
            input=self._build_input(
                document_title=document_title,
                card_type=card_type,
                claim_text=claim_text,
                card_summary=card_summary,
                evidence_spans=evidence_spans,
            ),
        )
        payload = response.model_dump(mode="python")
        output_text = getattr(response, "output_text", None) or _extract_output_text(payload)
        logs = _extract_logs(payload)

        process_parts = [output_text.strip() or "No final sandbox explanation was returned."]
        if logs:
            process_parts.append("## Python Logs\n```text\n" + "\n\n".join(logs).strip() + "\n```")
        full_process = "\n\n".join(part for part in process_parts if part.strip())
        summary = _extract_summary(output_text) or "Sandbox execution completed."

        return SandboxExecutionResult(
            status=SandboxRunStatus.COMPLETED,
            summary=summary,
            full_process=full_process,
        )

    def _build_input(
        self,
        *,
        document_title: str | None,
        card_type: CardType,
        claim_text: str | None,
        card_summary: str | None,
        evidence_spans: list[str],
    ) -> str:
        evidence_text = "\n".join(f"- {span}" for span in evidence_spans) or "- none"
        return f"""
Document title: {document_title or "unknown"}
Claim type: {card_type.value}
Claim text: {claim_text or "none"}
Claim summary: {card_summary or "none"}
Evidence spans:
{evidence_text}
""".strip()


def render_sandbox_html(*, title: str, summary: str, process: str) -> str:
    rendered_process = _render_markdown(process)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <style>
      body {{
        margin: 0;
        padding: 32px;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        background: #f8f4ec;
        color: #1f2329;
      }}
      main {{
        max-width: 980px;
        margin: 0 auto;
        background: rgba(255, 251, 245, 0.92);
        border: 1px solid rgba(31, 35, 41, 0.08);
        border-radius: 28px;
        padding: 28px;
        box-shadow: 0 24px 48px rgba(60, 51, 34, 0.08);
      }}
      h1 {{
        margin-top: 0;
        font-family: "Iowan Old Style", "Palatino Linotype", serif;
        font-size: 2rem;
      }}
      .summary {{
        margin-bottom: 24px;
        padding: 16px 18px;
        border-radius: 18px;
        background: #edf6f1;
        color: #1b5a52;
      }}
      .toolbar {{
        display: flex;
        gap: 10px;
        margin-bottom: 18px;
      }}
      .toolbar button {{
        border: 1px solid rgba(31, 35, 41, 0.12);
        background: #f2ece2;
        color: #52545a;
        border-radius: 999px;
        padding: 10px 14px;
        font: inherit;
        cursor: pointer;
      }}
      .toolbar button.is-active {{
        background: #1b5a52;
        color: #f8f4ec;
        border-color: #1b5a52;
      }}
      .view-panel.is-hidden {{
        display: none;
      }}
      .markdown-body {{
        padding: 20px 22px;
        border-radius: 20px;
        background: #fffdf8;
        border: 1px solid rgba(31, 35, 41, 0.08);
        line-height: 1.7;
      }}
      .markdown-body > :first-child {{
        margin-top: 0;
      }}
      .markdown-body > :last-child {{
        margin-bottom: 0;
      }}
      .markdown-body h1,
      .markdown-body h2,
      .markdown-body h3,
      .markdown-body h4,
      .markdown-body h5,
      .markdown-body h6 {{
        font-family: "Iowan Old Style", "Palatino Linotype", serif;
        line-height: 1.2;
        margin: 1.4em 0 0.6em;
      }}
      .markdown-body p,
      .markdown-body ul,
      .markdown-body ol,
      .markdown-body blockquote {{
        margin: 0 0 1em;
      }}
      .markdown-body ul,
      .markdown-body ol {{
        padding-left: 1.4em;
      }}
      .markdown-body blockquote {{
        padding: 0.2em 1em;
        border-left: 4px solid rgba(27, 90, 82, 0.25);
        background: #f6f1e8;
        color: #4e5055;
      }}
      .markdown-body code {{
        font-family: "SFMono-Regular", "Menlo", monospace;
        font-size: 0.95em;
        background: #f2ece2;
        padding: 0.15em 0.35em;
        border-radius: 8px;
      }}
      .markdown-body pre {{
        margin: 0 0 1em;
        padding: 18px;
        overflow-x: auto;
        border-radius: 18px;
        background: #f2ece2;
        border: 1px solid rgba(31, 35, 41, 0.08);
      }}
      .markdown-body pre code {{
        background: transparent;
        padding: 0;
        border-radius: 0;
      }}
      .markdown-body a {{
        color: #0d5b63;
      }}
      pre {{
        white-space: pre-wrap;
        word-break: break-word;
        margin: 0;
        padding: 20px;
        border-radius: 20px;
        background: #f2ece2;
        border: 1px solid rgba(31, 35, 41, 0.08);
        line-height: 1.6;
        font-family: "SFMono-Regular", "Menlo", monospace;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{escape(title)}</h1>
      <div class="summary">{escape(summary)}</div>
      <div class="toolbar" role="tablist" aria-label="Sandbox output format">
        <button id="rendered-tab" class="is-active" type="button" data-target="rendered-view">Rendered</button>
        <button id="markdown-tab" type="button" data-target="markdown-view">Markdown</button>
      </div>
      <section id="rendered-view" class="view-panel markdown-body">{rendered_process}</section>
      <pre id="markdown-view" class="view-panel is-hidden">{escape(process)}</pre>
    </main>
    <script>
      const tabs = Array.from(document.querySelectorAll(".toolbar button"));
      const panels = Array.from(document.querySelectorAll(".view-panel"));
      for (const tab of tabs) {{
        tab.addEventListener("click", () => {{
          for (const candidate of tabs) {{
            candidate.classList.toggle("is-active", candidate === tab);
          }}
          for (const panel of panels) {{
            panel.classList.toggle("is-hidden", panel.id !== tab.dataset.target);
          }}
        }});
      }}
    </script>
  </body>
</html>"""


def _render_markdown(text: str) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            class_attr = f' class="language-{escape(language)}"' if language else ""
            blocks.append(
                f"<pre><code{class_attr}>{escape(chr(10).join(code_lines))}</code></pre>"
            )
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            blocks.append(f"<h{level}>{_render_inline_markdown(heading_match.group(2))}</h{level}>")
            index += 1
            continue

        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip()[1:].lstrip())
                index += 1
            quote_text = " ".join(part for part in quote_lines if part)
            blocks.append(f"<blockquote><p>{_render_inline_markdown(quote_text)}</p></blockquote>")
            continue

        unordered_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if unordered_match:
            items: list[str] = []
            while index < len(lines):
                current = lines[index].strip()
                match = re.match(r"^[-*]\s+(.*)$", current)
                if not match:
                    break
                items.append(f"<li>{_render_inline_markdown(match.group(1))}</li>")
                index += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            items = []
            while index < len(lines):
                current = lines[index].strip()
                match = re.match(r"^\d+\.\s+(.*)$", current)
                if not match:
                    break
                items.append(f"<li>{_render_inline_markdown(match.group(1))}</li>")
                index += 1
            blocks.append("<ol>" + "".join(items) + "</ol>")
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            current = lines[index].strip()
            if not current:
                index += 1
                break
            if (
                current.startswith("```")
                or re.match(r"^(#{1,6})\s+", current)
                or current.startswith(">")
                or re.match(r"^[-*]\s+", current)
                or re.match(r"^\d+\.\s+", current)
            ):
                break
            paragraph_lines.append(current)
            index += 1
        blocks.append(f"<p>{_render_inline_markdown(' '.join(paragraph_lines))}</p>")

    return "\n".join(blocks) or "<p>No sandbox output was returned.</p>"


def _render_inline_markdown(text: str) -> str:
    escaped_text = escape(text)
    code_map: dict[str, str] = {}

    def stash_code(match: re.Match[str]) -> str:
        key = f"__CODE_{len(code_map)}__"
        code_map[key] = f"<code>{match.group(1)}</code>"
        return key

    rendered = re.sub(r"`([^`]+)`", stash_code, escaped_text)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda match: (
            f'<a href="{escape(match.group(2), quote=True)}" target="_blank" rel="noreferrer">'
            f"{match.group(1)}</a>"
        ),
        rendered,
    )
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"__(.+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", rendered)

    for key, html in code_map.items():
        rendered = rendered.replace(key, html)
    return rendered


def _extract_output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def _extract_logs(payload: dict[str, Any]) -> list[str]:
    logs: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "code_interpreter_call":
            continue
        for output in item.get("outputs") or []:
            if output.get("type") == "logs":
                log_text = output.get("logs")
                if isinstance(log_text, str) and log_text.strip():
                    logs.append(log_text.strip())
    return logs


def _extract_summary(output_text: str | None) -> str | None:
    if not output_text:
        return None
    for block in output_text.splitlines():
        line = block.strip()
        if not line:
            continue
        if line.lower().startswith("## summary"):
            continue
        return line[:240]
    return None
