from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models import Activity, ActivityRole, Dimension, Process, Role


def build_matrix(
    db: Session,
    process_id: int,
    dimension_slug: str,
) -> dict:
    process = (
        db.query(Process)
        .options(joinedload(Process.activities).joinedload(Activity.assignments))
        .filter(Process.id == process_id)
        .first()
    )
    if not process:
        return {"activities": [], "roles": [], "cells": {}}

    dimension = db.query(Dimension).filter(Dimension.slug == dimension_slug).first()
    roles = db.query(Role).order_by(Role.name).all()
    activities = sorted(process.activities, key=lambda a: a.sequence)
    cells: dict[str, str] = {}
    for act in activities:
        for ar in act.assignments:
            if dimension and ar.dimension_id == dimension.id:
                cells[f"{act.id}:{ar.role_id}"] = ar.letters or ""

    return {
        "process": process,
        "dimension": dimension,
        "activities": activities,
        "roles": roles,
        "cells": cells,
    }


def upsert_cell(
    db: Session,
    activity_id: int,
    role_id: int,
    dimension_id: int,
    letters: str,
) -> None:
    ar = (
        db.query(ActivityRole)
        .filter_by(activity_id=activity_id, role_id=role_id, dimension_id=dimension_id)
        .first()
    )
    if ar:
        ar.letters = letters.upper().strip()
    else:
        db.add(
            ActivityRole(
                activity_id=activity_id,
                role_id=role_id,
                dimension_id=dimension_id,
                letters=letters.upper().strip(),
            )
        )
    db.commit()
