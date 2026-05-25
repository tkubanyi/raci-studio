"""Unit tests for defect rule engine."""

from app.defects.engine import DefectEngine, Severity
from app.models import Activity, ActivityRole, Dimension, Process, Role


def _make_process_with_no_accountable():
    process = Process(id=1, name="Test", workspace_id=1)
    act = Activity(id=10, process_id=1, name="Step 1", sequence=1, is_start=True)
    role = Role(id=1, workspace_id=1, name="Analyst", in_hris=True)
    dim = Dimension(id=1, workspace_id=1, slug="ssc_ops", name="SSC")
    ar = ActivityRole(activity_id=10, role_id=1, dimension_id=1, letters="R")
    act.assignments = [ar]
    ar.role = role
    ar.dimension = dim
    process.activities = [act]
    return process, [role], dim


def test_d001_no_accountable():
    process, roles, dim = _make_process_with_no_accountable()
    engine = DefectEngine()
    defects = engine.scan_process(process, roles, dim.id, dim.slug)
    rules = {d.rule_id for d in defects}
    assert "D-001" in rules
    d001 = next(d for d in defects if d.rule_id == "D-001")
    assert d001.severity == Severity.CRITICAL


def test_d003_no_responsible():
    process = Process(id=1, name="Test", workspace_id=1)
    act = Activity(
        id=10,
        process_id=1,
        name="Step 1",
        sequence=1,
        is_start=True,
        sla="1d",
        frequency="Daily",
    )
    role = Role(id=1, workspace_id=1, name="Manager", in_hris=True)
    dim = Dimension(id=1, workspace_id=1, slug="pdlc", name="PDLC")
    ar = ActivityRole(activity_id=10, role_id=1, dimension_id=1, letters="R")
    act.assignments = [ar]
    ar.role = role
    process.activities = [act]
    engine = DefectEngine()
    defects = engine.scan_process(process, [role], dim.id, dim.slug)
    assert "D-003" not in {d.rule_id for d in defects}
    ar.letters = "I"
    defects = engine.scan_process(process, [role], dim.id, dim.slug)
    assert "D-003" in {d.rule_id for d in defects}
