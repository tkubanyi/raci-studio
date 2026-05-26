"""Visio-like swimlane diagram model, rendering, and persistence."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Activity, Process


def diagram_from_process(
    process: Process,
    activities: list[Activity],
    role_names: dict[int, str] | None = None,
) -> dict:
    """Build diagram JSON from DB activities (grouped by primary RACI role per step)."""
    role_names = role_names or {}
    lanes_map: dict[str, str] = {}
    nodes: list[dict] = []
    edges: list[dict] = []
    prev_id: str | None = None
    sorted_acts = sorted(activities, key=lambda a: a.sequence)

    for i, act in enumerate(sorted_acts):
        lane_label = "Process"
        if act.assignments:
            ar = act.assignments[0]
            lane_label = role_names.get(ar.role_id, getattr(ar.role, "name", None) or "Role")
        lane_id = re.sub(r"[^a-z0-9]+", "_", lane_label.lower()).strip("_") or "lane_default"
        lanes_map[lane_id] = lane_label
        node_id = f"a{act.id}"
        ntype = "start" if act.is_start or i == 0 else "task"
        if act.name and "?" in act.name:
            ntype = "decision"
        nodes.append(
            {
                "id": node_id,
                "lane_id": lane_id,
                "label": act.name,
                "type": ntype,
                "activity_id": act.id,
            }
        )
        if prev_id:
            edges.append({"from": prev_id, "to": node_id, "label": ""})
        if act.predecessor_ids:
            for pred in act.predecessor_ids.split(","):
                if pred.strip().isdigit():
                    edges.append({"from": f"a{pred.strip()}", "to": node_id, "label": ""})
        prev_id = node_id

    return {
        "title": process.name,
        "lanes": [{"id": k, "label": v} for k, v in lanes_map.items()],
        "nodes": nodes,
        "edges": edges,
    }


def merge_diagram_with_activities(diagram: dict | None, activities: list[dict]) -> dict:
    if diagram and diagram.get("nodes"):
        return diagram
    from app.services.extraction import _build_diagram_from_activities

    return _build_diagram_from_activities(activities)


def _safe_label(value: str) -> str:
    return value.replace(chr(34), "'").replace("\n", " ")


def render_mermaid_swimlane(diagram: dict) -> str:
    lanes = diagram.get("lanes") or []
    nodes = diagram.get("nodes") or []
    edges = diagram.get("edges") or []
    if not nodes:
        return "flowchart LR\n    Empty[No diagram data]"

    lines = ["flowchart TB"]
    for lane in lanes:
        lid = lane.get("id", "lane")
        label = _safe_label(str(lane.get("label") or lid))
        lines.append(f'    subgraph {lid}["{label}"]')
        lane_nodes = [n for n in nodes if n.get("lane_id") == lid]
        for n in lane_nodes:
            nid = n.get("id", "n")
            nl = _safe_label(str(n.get("label") or nid))
            ntype = n.get("type", "task")
            if ntype == "start":
                lines.append(f"        {nid}([{nl}])")
            elif ntype == "end":
                lines.append(f"        {nid}([{nl}])")
            elif ntype == "decision":
                lines.append(f"        {nid}{{{nl}}}")
            else:
                lines.append(f'        {nid}["{nl}"]')
        lines.append("    end")

    for e in edges:
        fr, to = e.get("from"), e.get("to")
        if fr and to:
            lbl = e.get("label") or ""
            if lbl:
                lines.append(f"    {fr} -->|{lbl}| {to}")
            else:
                lines.append(f"    {fr} --> {to}")

    return "\n".join(lines)


def parse_diagram_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def diagram_json_dumps(diagram: dict) -> str:
    return json.dumps(diagram, indent=2)
