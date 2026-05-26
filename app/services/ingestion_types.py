"""Types for multi-format document ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IngestionResult:
    text: str
    source_type: str
    filename: str
    image_paths: list[Path] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def has_visual_content(self) -> bool:
        return bool(self.image_paths) or self.source_type in ("image", "vsdx", "pdf_scanned")
