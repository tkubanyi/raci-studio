"""Persist extracted SOP content as processes, activities, and RACI assignments."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.models import DIMENSION_SLUGS, Activity, ActivityRole, Dimension, Document, Process, Role
from app.services.diagram import diagram_from_process, diagram_json_dumps, merge_diagram_with_activities
from app.services.extraction import ExtractionResult


def _normalize_role_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:200]


def _get_or_create_role(db: Session, workspace_id: int, name: str, department: str | None = None) -> Role:
    clean = _normalize_role_name(name)
    if not clean or clean.lower() in ("unassigned", "n/a", "tbd"):
        clean = "Unassigned Role"
    existing = (
        db.query(Role)
        .filter(Role.workspace_id == workspace_id, Role.name.ilike(clean))
        .first()
    )
    if existing:
        return existing
    role = Role(workspace_id=workspace_id, name=clean, department=department, in_hris=True, fte=1.0)
    db.add(role)
    db.flush()
    return role


def _raci_letters(hint: str | None) -> str:
    if not hint:
        return "R"
    letters = "".join(c for c in hint.upper() if c in "RACI")
    return letters or "R"


def import_from_extraction(
    db: Session,
    workspace_id: int,
    result: ExtractionResult,
    *,
    source_filename: str | None = None,
    document_id: int | None = None,
    domain: str = "Finance",
) -> list[int]:
    """
    Create processes and activities from an extraction result.
    Returns list of created process IDs.
    """
    dimensions = {d.slug: d for d in db.query(Dimension).filter(Dimension.workspace_id == workspace_id).all()}
    if not dimensions:
        raise ValueError("Workspace has no RACI dimensions configured.")

    role_cache: dict[str, Role] = {}
    for r in db.query(Role).filter(Role.workspace_id == workspace_id).all():
        role_cache[r.name.lower()] = r

    for role_data in result.roles:
        name = role_data.get("name") if isinstance(role_data, dict) else str(role_data)
        dept = role_data.get("department") if isinstance(role_data, dict) else None
        role = _get_or_create_role(db, workspace_id, name, dept)
        role_cache[role.name.lower()] = role

    created_ids: list[int] = []
    processes = result.processes or []
    if not processes and result.ambiguities:
        processes = [{"name": "Extracted Process", "owner": "Process Owner", "activities": []}]

    stem = Path(source_filename or "document").stem.replace("_", " ").replace("-", " ")[:120]

    for idx, proc_data in enumerate(processes):
        if not isinstance(proc_data, dict):
            continue
        proc_name = (proc_data.get("name") or "").strip()
        if not proc_name or proc_name == "Extracted Process":
            proc_name = stem if len(processes) == 1 else f"{stem} ({idx + 1})"
        owner_name = proc_data.get("owner") or "Process Owner"
        owner = _get_or_create_role(db, workspace_id, owner_name)
        role_cache[owner.name.lower()] = owner

        narrative = (proc_data.get("process_description") or "").strip()
        desc_parts = []
        if narrative:
            desc_parts.append(narrative)
        desc_parts.append(f"Imported from: {source_filename or 'upload'} (mode: {result.mode}).")
        if document_id:
            desc_parts.append(f"Document ID: {document_id}.")

        diagram = merge_diagram_with_activities(
            result.diagram if idx == 0 else proc_data.get("diagram"),
            proc_data.get("activities") or [],
        )

        process = Process(
            workspace_id=workspace_id,
            name=proc_name[:200],
            domain=domain,
            description="\n\n".join(desc_parts),
            status="draft",
            version="0.1",
            owner_role_id=owner.id,
            diagram_json=diagram_json_dumps(diagram) if diagram else None,
        )
        db.add(process)
        db.flush()
        created_ids.append(process.id)

        activities_data = proc_data.get("activities") or []
        prev_act_id: int | None = None
        for act_idx, act_data in enumerate(activities_data):
            if not isinstance(act_data, dict):
                continue
            act_name = (act_data.get("name") or f"Step {act_idx + 1}").strip()[:200]
            sequence = int(act_data.get("sequence") or act_idx + 1)
            actor = act_data.get("actor") or owner_name
            raci_hint = act_data.get("raci_hint")

            act = Activity(
                process_id=process.id,
                name=act_name,
                description=act_data.get("description"),
                sequence=sequence,
                is_start=act_idx == 0,
                predecessor_ids=str(prev_act_id) if prev_act_id else None,
                sla=act_data.get("sla"),
                frequency=act_data.get("frequency"),
            )
            db.add(act)
            db.flush()
            prev_act_id = act.id

            actor_role = _get_or_create_role(db, workspace_id, actor)
            role_cache[actor_role.name.lower()] = actor_role
            letters = _raci_letters(raci_hint)
            for slug in DIMENSION_SLUGS:
                dim = dimensions.get(slug)
                if dim:
                    db.add(
                        ActivityRole(
                            activity_id=act.id,
                            role_id=actor_role.id,
                            dimension_id=dim.id,
                            letters=letters,
                        )
                    )

        acts = (
            db.query(Activity)
            .options(joinedload(Activity.assignments).joinedload(ActivityRole.role))
            .filter(Activity.process_id == process.id)
            .order_by(Activity.sequence)
            .all()
        )
        if acts:
            process.diagram_json = diagram_json_dumps(diagram_from_process(process, acts))

    db.commit()
    return created_ids


def extraction_summary_payload(
    result: ExtractionResult,
    created_process_ids: list[int],
) -> dict:
    return {
        "mode": result.mode,
        "source_type": result.source_type,
        "processes": result.processes,
        "roles": result.roles,
        "ambiguities": result.ambiguities,
        "diagram": result.diagram,
        "created_process_ids": created_process_ids,
    }


def delete_process(db: Session, process_id: int) -> bool:
    process = db.query(Process).filter(Process.id == process_id).first()
    if not process:
        return False
    db.delete(process)
    db.commit()
    return True


def delete_document(db: Session, document_id: int, *, delete_file: bool = True) -> bool:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return False
    if delete_file:
        try:
            Path(doc.storage_path).unlink(missing_ok=True)
        except OSError:
            pass
    db.delete(doc)
    db.commit()
    return True
