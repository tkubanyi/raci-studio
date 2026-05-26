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


def enrich_diagram_with_raci(
    diagram: dict,
    activities: list,
    dimension_id: int,
    roles_by_id: dict[int, str] | None = None,
) -> dict:
    """Attach RACI overlay badges to each node linked to an activity."""
    roles_by_id = roles_by_id or {}
    act_map = {a.id: a for a in activities}
    out = {**diagram, "lanes": list(diagram.get("lanes") or []), "nodes": [], "edges": list(diagram.get("edges") or [])}

    for node in diagram.get("nodes") or []:
        n = {**node}
        aid = node.get("activity_id")
        if aid and aid in act_map:
            act = act_map[aid]
            overlay = []
            for ar in act.assignments:
                if ar.dimension_id == dimension_id and (ar.letters or "").strip():
                    overlay.append(
                        {
                            "role_id": ar.role_id,
                            "role_name": roles_by_id.get(ar.role_id)
                            or (ar.role.name if getattr(ar, "role", None) else f"Role {ar.role_id}"),
                            "letters": (ar.letters or "").upper(),
                        }
                    )
            overlay.sort(key=lambda x: x["role_name"])
            n["raci_overlay"] = overlay
        else:
            n["raci_overlay"] = []
        out["nodes"].append(n)
    return out


def _lane_id_for_role_name(role_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", role_name.lower()).strip("_") or "lane_default"


def apply_diagram_to_database(
    db,
    process,
    diagram: dict,
    dimension_id: int,
    *,
    workspace_id: int,
) -> None:
    """Persist diagram edits: activity names, order, lanes (primary R), RACI overlays."""
    from app.models import Activity, ActivityRole, Role

    lanes_by_id = {l["id"]: l.get("label", l["id"]) for l in diagram.get("lanes") or []}
    nodes = list(diagram.get("nodes") or [])
    edges = diagram.get("edges") or []

    # Topological order from edges, fallback to list order
    ordered_ids: list[str] = []
    node_ids = {n["id"] for n in nodes}
    targets = {e["to"] for e in edges if e.get("to") in node_ids}
    starts = [n["id"] for n in nodes if n["id"] not in targets]
    if not starts and nodes:
        starts = [nodes[0]["id"]]
    visited: set[str] = set()

    def walk(nid: str) -> None:
        if nid in visited:
            return
        visited.add(nid)
        ordered_ids.append(nid)
        for e in edges:
            if e.get("from") == nid and e.get("to") in node_ids:
                walk(e["to"])

    for s in starts:
        walk(s)
    for n in nodes:
        if n["id"] not in visited:
            ordered_ids.append(n["id"])

    id_to_node = {n["id"]: n for n in nodes}
    prev_db_id: int | None = None

    for seq, nid in enumerate(ordered_ids, start=1):
        node = id_to_node.get(nid)
        if not node:
            continue
        lane_label = lanes_by_id.get(node.get("lane_id"), "Process")
        activity_id = node.get("activity_id")

        if activity_id:
            act = db.query(Activity).filter(Activity.id == activity_id, Activity.process_id == process.id).first()
        else:
            act = None

        if not act:
            act = Activity(
                process_id=process.id,
                name=(node.get("label") or f"Step {seq}")[:200],
                sequence=seq,
                is_start=seq == 1,
            )
            db.add(act)
            db.flush()
            node["activity_id"] = act.id
        else:
            act.name = (node.get("label") or act.name)[:200]
            act.sequence = seq
            act.is_start = seq == 1
            act.predecessor_ids = str(prev_db_id) if prev_db_id else None

        ntype = node.get("type") or "task"
        if ntype == "decision":
            pass

        # Apply RACI overlay from editor
        for item in node.get("raci_overlay") or []:
            rid = item.get("role_id")
            letters = (item.get("letters") or "").upper()
            if rid and letters:
                ar = (
                    db.query(ActivityRole)
                    .filter_by(activity_id=act.id, role_id=rid, dimension_id=dimension_id)
                    .first()
                )
                if ar:
                    ar.letters = letters
                else:
                    db.add(
                        ActivityRole(
                            activity_id=act.id,
                            role_id=rid,
                            dimension_id=dimension_id,
                            letters=letters,
                        )
                    )

        # Ensure lane role has at least R on this dimension if overlay empty
        lane_role = (
            db.query(Role)
            .filter(Role.workspace_id == workspace_id, Role.name.ilike(lane_label.strip()))
            .first()
        )
        if not lane_role:
            lane_role = Role(workspace_id=workspace_id, name=lane_label[:200], in_hris=True, fte=1.0)
            db.add(lane_role)
            db.flush()

        has_r = any(
            (item.get("letters") or "").upper().find("R") >= 0 for item in (node.get("raci_overlay") or [])
        )
        if not has_r:
            ar = (
                db.query(ActivityRole)
                .filter_by(activity_id=act.id, role_id=lane_role.id, dimension_id=dimension_id)
                .first()
            )
            if ar:
                if "R" not in (ar.letters or "").upper():
                    ar.letters = ((ar.letters or "") + "R").upper()
            else:
                db.add(
                    ActivityRole(
                        activity_id=act.id,
                        role_id=lane_role.id,
                        dimension_id=dimension_id,
                        letters="R",
                    )
                )

        prev_db_id = act.id

    process.diagram_json = diagram_json_dumps(diagram)
    db.commit()
