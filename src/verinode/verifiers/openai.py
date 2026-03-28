from __future__ import annotations

from openai import OpenAI

from verinode.models import ClaimKind
from verinode.prompts import REFERENCE_VERIFICATION_SYSTEM_PROMPT
from verinode.verification_types import ReferenceVerificationResult


class OpenAIReferenceVerifier:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def verify(
        self,
        *,
        document_title: str | None,
        claim_text: str | None,
        claim_kind: ClaimKind,
        card_summary: str | None,
        evidence_spans: list[str],
        relation_type: str,
        ref_label: str | None,
        raw_citation: str,
        resolved_title: str | None,
        resolved_url: str | None,
        resolved_doi: str | None,
    ) -> ReferenceVerificationResult:
        response = self._client.responses.parse(
            model=self._model,
            tools=[{"type": "web_search"}],
            input=[
                {"role": "system", "content": REFERENCE_VERIFICATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_input(
                                document_title=document_title,
                                claim_text=claim_text,
                                claim_kind=claim_kind,
                                card_summary=card_summary,
                                evidence_spans=evidence_spans,
                                relation_type=relation_type,
                                ref_label=ref_label,
                                raw_citation=raw_citation,
                                resolved_title=resolved_title,
                                resolved_url=resolved_url,
                                resolved_doi=resolved_doi,
                            ),
                        }
                    ],
                },
            ],
            text_format=ReferenceVerificationResult,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise ValueError("openai_verification_empty")
        return parsed

    def _build_input(
        self,
        *,
        document_title: str | None,
        claim_text: str | None,
        claim_kind: ClaimKind,
        card_summary: str | None,
        evidence_spans: list[str],
        relation_type: str,
        ref_label: str | None,
        raw_citation: str,
        resolved_title: str | None,
        resolved_url: str | None,
        resolved_doi: str | None,
    ) -> str:
        evidence_text = "\n".join(f"- {span}" for span in evidence_spans) or "- none"
        return f"""
Document title: {document_title or "unknown"}
Claim kind: {claim_kind.value}
Claim text: {claim_text or "none"}
Card summary: {card_summary or "none"}
Document evidence spans:
{evidence_text}

Relation type: {relation_type}
Reference label: {ref_label or "none"}
Raw citation: {raw_citation}
Resolved title: {resolved_title or "none"}
Resolved URL: {resolved_url or "none"}
Resolved DOI: {resolved_doi or "none"}
""".strip()
