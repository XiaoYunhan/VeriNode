from __future__ import annotations

import base64

from openai import OpenAI

from verinode.extraction_types import ExtractionResult
from verinode.models import FileType
from verinode.prompts import CLAIM_EXTRACTION_SYSTEM_PROMPT


class OpenAIClaimExtractor:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def extract(
        self,
        *,
        filename: str,
        file_type: FileType,
        content: bytes,
    ) -> ExtractionResult:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": CLAIM_EXTRACTION_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": self._build_user_content(
                        filename=filename,
                        file_type=file_type,
                        content=content,
                    ),
                },
            ],
            text_format=ExtractionResult,
        )

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise ValueError("openai_extraction_empty")
        return parsed

    def _build_user_content(
        self,
        *,
        filename: str,
        file_type: FileType,
        content: bytes,
    ) -> list[dict[str, str]]:
        instruction = {
            "type": "input_text",
            "text": (
                "Extract verification cards from this document. "
                "Use only information present in the file."
            ),
        }
        if file_type is FileType.PDF:
            encoded = base64.b64encode(content).decode("utf-8")
            return [
                instruction,
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:application/pdf;base64,{encoded}",
                },
            ]

        return [
            instruction,
            {
                "type": "input_text",
                "text": content.decode("utf-8"),
            },
        ]

