"""Tests for SOP → process import."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Activity, Process
from app.seed import seed_database
from app.services.extraction import ExtractionResult
from app.services.process_import import import_from_extraction


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed_database(session)
    yield session
    session.close()


def test_import_creates_process_and_activities(db):
    ws = db.query(Process).first().workspace_id
    result = ExtractionResult(
        processes=[
            {
                "name": "Test SOP Process",
                "owner": "Billing Analyst",
                "activities": [
                    {"name": "Receive order", "actor": "Billing Analyst", "raci_hint": "R", "sequence": 1},
                    {"name": "Approve credit", "actor": "Credit Controller", "raci_hint": "A", "sequence": 2},
                ],
            }
        ],
        roles=[{"name": "Billing Analyst", "department": "Finance"}],
        ambiguities=[],
        mode="test",
    )
    ids = import_from_extraction(db, ws, result, source_filename="order_sop.txt", document_id=99)
    assert len(ids) == 1
    proc = db.query(Process).filter(Process.id == ids[0]).first()
    assert proc is not None
    assert proc.name == "Test SOP Process"
    assert "order_sop.txt" in (proc.description or "")
    acts = db.query(Activity).filter(Activity.process_id == ids[0]).order_by(Activity.sequence).all()
    assert len(acts) == 2
    assert acts[0].is_start
    assert acts[1].predecessor_ids == str(acts[0].id)
