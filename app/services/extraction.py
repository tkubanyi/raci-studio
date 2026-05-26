"""Heuristic and structured process extraction from document text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import get_settings


@dataclass
class ExtractedActivity:
    name: str
    actor: str
    raci_hint: str
    confidence: float


@dataclass
class ExtractionResult:
    processes: list[dict]
    roles: list[dict]
    ambiguities: list[dict]
    mode: str
    diagram: dict | None = None
    source_type: str = "text"

    def primary_process_description(self) -> str | None:
        if not self.processes:
            return None
        p = self.processes[0]
        if isinstance(p, dict):
            return p.get("process_description")
        return None


def _build_diagram_from_activities(activities: list[dict]) -> dict:
    lanes_map: dict[str, str] = {}
    nodes: list[dict] = []
    edges: list[dict] = []
    prev_id: str | None = None

    for i, act in enumerate(activities):
        if not isinstance(act, dict):
            continue
        actor = (act.get("actor") or "Unassigned").strip()[:80]
        lane_id = re.sub(r"[^a-z0-9]+", "_", actor.lower()).strip("_") or "lane_unassigned"
        if lane_id not in lanes_map:
            lanes_map[lane_id] = actor
        node_id = f"n{i + 1}"
        ntype = "start" if i == 0 else "end" if i == len(activities) - 1 else "task"
        if act.get("gateway") == "decision":
            ntype = "decision"
        nodes.append(
            {
                "id": node_id,
                "lane_id": lane_id,
                "label": (act.get("name") or f"Step {i + 1}")[:120],
                "type": ntype,
            }
        )
        if prev_id:
            edges.append({"from": prev_id, "to": node_id, "label": ""})
        prev_id = node_id

    return {
        "lanes": [{"id": lid, "label": lbl} for lid, lbl in lanes_map.items()],
        "nodes": nodes,
        "edges": edges,
    }


def heuristic_extract(
    text: str,
    *,
    filename: str | None = None,
    source_type: str = "text",
) -> ExtractionResult:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    activities: list[ExtractedActivity] = []
    roles: set[str] = set()
    step_re = re.compile(r"^(\d+[\.\)]\s*|-\s*|\u2022\s*)(.+)$", re.I)
    arrow_re = re.compile(r"(.+?)\s*(-+>|→|=>)\s*(.+)", re.I)

    for line in lines[:300]:
        m = step_re.match(line)
        if m:
            name = m.group(2)[:120]
            raci = "R"
            if re.search(r"\b(approv|sign.?off|authoriz)\b", name, re.I):
                raci = "A"
            elif re.search(r"\b(consult|review)\b", name, re.I):
                raci = "C"
            elif re.search(r"\b(inform|notify)\b", name, re.I):
                raci = "I"
            actor = "Unassigned"
            role_m = re.search(r"\(([^)]+)\)", name)
            if role_m:
                actor = role_m.group(1).strip()[:80]
                roles.add(actor)
            activities.append(ExtractedActivity(name, actor, raci, 0.55))
            continue
        am = arrow_re.match(line)
        if am:
            activities.append(ExtractedActivity(am.group(1).strip()[:120], "Unassigned", "R", 0.5))
            activities.append(ExtractedActivity(am.group(3).strip()[:120], "Unassigned", "R", 0.5))
            continue
        if re.search(r"\b(role|owner|responsible|swimlane|lane)\b", line, re.I):
            parts = re.split(r"[:–-]", line, maxsplit=1)
            if len(parts) == 2:
                roles.add(parts[1].strip()[:80])

    if not activities and lines:
        for line in lines[:20]:
            if len(line) > 8 and not line.startswith("["):
                activities.append(ExtractedActivity(line[:100], "Unassigned", "R", 0.4))

    stem = Path(filename or "document").stem.replace("_", " ").replace("-", " ")
    owner = next(iter(roles), None) or "Process Owner"
    act_dicts = [
        {
            "name": a.name,
            "actor": a.actor,
            "raci_hint": a.raci_hint,
            "confidence": a.confidence,
            "sequence": i + 1,
            "description": "",
        }
        for i, a in enumerate(activities)
    ]
    narrative = (
        f"This process was heuristically extracted from {filename or 'the uploaded document'}. "
        f"It comprises {len(act_dicts)} steps. Configure OPENAI_API_KEY for richer narrative and Visio-quality diagrams."
    )
    proc = {
        "name": stem[:120] if stem else "Extracted Process",
        "owner": owner,
        "process_description": narrative,
        "activities": act_dicts,
    }
    diagram = _build_diagram_from_activities(act_dicts)
    return ExtractionResult(
        processes=[proc] if act_dicts else [],
        roles=[{"name": r, "department": None} for r in roles],
        ambiguities=[
            {
                "sentence": "Heuristic extraction",
                "reason": "Add OPENAI_API_KEY for AI understanding of images, PDF scans, and Visio charts.",
            }
        ],
        mode="heuristic",
        diagram=diagram,
        source_type=source_type,
    )


async def llm_extract(text: str, filename: str | None = None) -> ExtractionResult:
    """Legacy entry — prefer extract_processes_from_document."""
    from app.services.ai.extractor import extract_processes_from_document
    from app.services.ingestion_types import IngestionResult

    ing = IngestionResult(text=text, source_type="text", filename=filename or "document.txt")
    return await extract_processes_from_document(ing, filename=filename)
