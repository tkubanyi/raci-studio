"""Multi-format document ingestion: Word, PDF, images, Visio, PowerPoint, Excel."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.config import get_settings
from app.services.ingestion.parsers import (
    extract_docx,
    extract_image,
    extract_pdf,
    extract_pptx,
    extract_txt_md,
    extract_vsdx,
    extract_xlsx,
)
from app.services.ingestion_types import IngestionResult

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".docx",
    ".pdf",
    ".pptx",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".vsdx",
    ".vsdm",
}


def ingest_file(path: Path, filename: str | None = None) -> IngestionResult:
    """Read file content and optional page images for AI vision."""
    settings = get_settings()
    name = filename or path.name
    ext = Path(name).suffix.lower()
    work_dir = settings.upload_dir / "ingest_cache" / uuid.uuid4().hex[:12]
    work_dir.mkdir(parents=True, exist_ok=True)

    if ext in (".txt", ".md"):
        return IngestionResult(
            text=extract_txt_md(path),
            source_type="text",
            filename=name,
            metadata={"extension": ext},
        )

    if ext == ".docx":
        return IngestionResult(
            text=extract_docx(path),
            source_type="word",
            filename=name,
            metadata={"extension": ext},
        )

    if ext == ".pdf":
        text, images = extract_pdf(path, work_dir)
        return IngestionResult(
            text=text,
            source_type="pdf_scanned" if images and len(text) < 200 else "pdf",
            filename=name,
            image_paths=images,
            metadata={"extension": ext, "page_images": len(images)},
        )

    if ext in (".pptx",):
        return IngestionResult(
            text=extract_pptx(path),
            source_type="powerpoint",
            filename=name,
            metadata={"extension": ext},
        )

    if ext in (".xlsx", ".xls"):
        return IngestionResult(
            text=extract_xlsx(path) if ext == ".xlsx" else "[Legacy .xls — save as .xlsx]",
            source_type="excel",
            filename=name,
            metadata={"extension": ext},
        )

    if ext in (".vsdx", ".vsdm"):
        return IngestionResult(
            text=extract_vsdx(path),
            source_type="visio",
            filename=name,
            metadata={"extension": ext},
        )

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        text, images = extract_image(path, work_dir)
        return IngestionResult(
            text=text,
            source_type="image",
            filename=name,
            image_paths=images,
            metadata={"extension": ext},
        )

    raise ValueError(
        f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def extract_text_from_file(path: Path, filename: str) -> str:
    """Backward-compatible text-only API."""
    return ingest_file(path, filename).text
