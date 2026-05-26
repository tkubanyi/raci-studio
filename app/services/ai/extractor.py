"""AI-powered process understanding from ingested documents (text + vision)."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import httpx

from app.config import get_settings
from app.services.extraction import ExtractionResult, heuristic_extract
from app.services.ingestion_types import IngestionResult

EXTRACTION_SCHEMA = """
Return a single JSON object with this structure:
{
  "processes": [{
    "name": "Process name",
    "owner": "Role name of process owner",
    "process_description": "2-4 sentence narrative of the end-to-end process",
    "activities": [{
      "name": "Activity label",
      "description": "What happens in this step",
      "actor": "Swimlane role or department",
      "raci_hint": "R or A or C or I",
      "sequence": 1,
      "inputs": "optional",
      "outputs": "optional",
      "systems": "optional",
      "sla": "optional",
      "frequency": "optional",
      "gateway": "none|decision|parallel"
    }]
  }],
  "roles": [{"name": "Role", "department": "optional"}],
  "ambiguities": [{"sentence": "...", "reason": "..."}],
  "diagram": {
    "lanes": [{"id": "lane_1", "label": "Role or system lane name"}],
    "nodes": [{"id": "n1", "lane_id": "lane_1", "label": "Step name", "type": "start|task|decision|end"}],
    "edges": [{"from": "n1", "to": "n2", "label": "optional"}]
  }
}
Rules:
- Infer swimlanes from actors/roles in Visio-like or SOP documents.
- Preserve step order via sequence and edges.
- Use RACI hints from verbs (approve→A, perform→R, consult→C, inform→I).
- Never invent roles not supported by the document.
- If multiple processes exist, return multiple entries in processes[].
"""


def _encode_image(path: Path) -> tuple[str, str]:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return mime, data


async def _openai_extract(
    text: str,
    image_paths: list[Path],
    filename: str,
    source_type: str,
) -> ExtractionResult:
    settings = get_settings()
    model = settings.openai_vision_model if image_paths else settings.openai_model

    user_parts: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Analyze this operating model document and extract structured process data.\n"
                f"Filename: {filename}\nSource type: {source_type}\n\n"
                f"{EXTRACTION_SCHEMA}\n\n--- DOCUMENT TEXT ---\n{text[:14000]}"
            ),
        }
    ]
    for img in image_paths[:4]:
        if not img.exists():
            continue
        mime, b64 = _encode_image(img)
        user_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
            }
        )

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert in process mapping, BPMN, and RACI for shared service "
                            "centers. Output valid JSON only."
                        ),
                    },
                    {"role": "user", "content": user_parts},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)

    mode = "llm-vision" if image_paths else "llm"
    return ExtractionResult(
        processes=data.get("processes", []),
        roles=data.get("roles", []),
        ambiguities=data.get("ambiguities", []),
        mode=mode,
        diagram=data.get("diagram"),
        source_type=source_type,
    )


async def extract_processes_from_document(
    ingestion: IngestionResult,
    *,
    filename: str | None = None,
) -> ExtractionResult:
    """Run AI extraction when configured; otherwise enhanced heuristic."""
    settings = get_settings()
    fname = filename or ingestion.filename
    text = ingestion.text or ""

    if settings.has_llm:
        try:
            return await _openai_extract(
                text,
                ingestion.image_paths if ingestion.has_visual_content else [],
                fname,
                ingestion.source_type,
            )
        except Exception:
            pass

    result = heuristic_extract(text, filename=fname, source_type=ingestion.source_type)
    if ingestion.source_type == "visio":
        result.ambiguities.append(
            {
                "sentence": fname,
                "reason": "Visio parsed as shape labels — set OPENAI_API_KEY for full diagram understanding.",
            }
        )
    return result
