"""AC-2: seeded Order-to-Cash triggers all twelve rule-based defect rules."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.defects.engine import DefectEngine
from app.models import Dimension, Process
from app.seed import seed_database


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed_database(session)
    yield session
    session.close()


def test_seed_o2c_exists(db):
    otc = db.query(Process).filter(Process.name.like("%Order-to-Cash%")).first()
    assert otc is not None
    assert len(otc.activities) >= 7


def test_all_twelve_rules_on_seeded_o2c(db):
    otc = db.query(Process).filter(Process.name.like("%Order-to-Cash%")).first()
    dimensions = db.query(Dimension).all()
    from app.models import Role

    roles = db.query(Role).all()
    engine = DefectEngine(role_overload_threshold=0.30, allow_r_equals_a=False)
    rule_ids: set[str] = set()
    for dim in dimensions:
        defects = engine.scan_process(otc, roles, dim.id, dim.slug)
        rule_ids.update(d.rule_id for d in defects)

    expected = {f"D-{i:03d}" for i in range(1, 13)}
    missing = expected - rule_ids
    assert not missing, f"Missing rules on seed data: {missing}. Found: {sorted(rule_ids)}"
