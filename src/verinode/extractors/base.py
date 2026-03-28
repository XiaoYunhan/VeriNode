from __future__ import annotations

from typing import Protocol

from verinode.extraction_types import ExtractionResult
from verinode.models import FileType


class ClaimExtractor(Protocol):
    def extract(
        self,
        *,
        filename: str,
        file_type: FileType,
        content: bytes,
    ) -> ExtractionResult: ...

