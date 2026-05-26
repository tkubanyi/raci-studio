"""Tests for diagram RACI overlay and persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Activity, ActivityRole, Dimension, Process, Role
from app.seed import seed_database
from app.services.diagram import (
    apply_diagram_to_database,
    diagram_from_process,
    enrich_diagram_with_raci,
    parse_diagram_json,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    seed_database(session)
    yield session
    session.close()


@pytest.fixture
def process_with_activity(db: Session):
    ws_id = db.query(Dimension).first().workspace_id
    dim = db.query(Dimension).filter_by(slug="ssc_ops").first()
    proc = Process(workspace_id=ws_id, name="Test Proc", domain="Finance")
    db.add(proc)
    db.flush()
    role = Role(workspace_id=ws_id, name="Analyst", in_hris=True, fte=1.0)
    db.add(role)
    db.flush()
    act = Activity(process_id=proc.id, name="Review invoice", sequence=1, is_start=True)
    db.add(act)
    db.flush()
    db.add(
        ActivityRole(
            activity_id=act.id,
            role_id=role.id,
            dimension_id=dim.id,
            letters="RA",
        )
    )
    db.commit()
    db.refresh(proc)
    db.refresh(act)
    return proc, act, role, dim


def test_enrich_diagram_with_raci(db: Session, process_with_activity):
    proc, act, role, dim = process_with_activity
    acts = list(proc.activities)
    diagram = diagram_from_process(proc, acts, role_names={role.id: role.name})
    enriched = enrich_diagram_with_raci(diagram, acts, dim.id, {role.id: role.name})
    node = enriched["nodes"][0]
    assert node["activity_id"] == act.id
    assert len(node["raci_overlay"]) == 1
    assert node["raci_overlay"][0]["letters"] == "RA"
    assert node["raci_overlay"][0]["role_name"] == "Analyst"


def test_apply_diagram_updates_activity_and_raci(db: Session, process_with_activity):
    proc, act, role, dim = process_with_activity
    diagram = {
        "title": proc.name,
        "lanes": [{"id": "lane_analyst", "label": "Analyst"}],
        "nodes": [
            {
                "id": f"a{act.id}",
                "lane_id": "lane_analyst",
                "label": "Updated step name",
                "type": "task",
                "activity_id": act.id,
                "raci_overlay": [
                    {"role_id": role.id, "role_name": role.name, "letters": "A"},
                ],
            }
        ],
        "edges": [],
    }
    apply_diagram_to_database(db, proc, diagram, dim.id, workspace_id=proc.workspace_id)
    db.refresh(act)
    assert act.name == "Updated step name"
    ar = (
        db.query(ActivityRole)
        .filter_by(activity_id=act.id, role_id=role.id, dimension_id=dim.id)
        .first()
    )
    assert ar is not None
    assert "A" in (ar.letters or "").upper()
    stored = parse_diagram_json(proc.diagram_json)
    assert stored is not None
    assert stored["nodes"][0]["label"] == "Updated step name"
