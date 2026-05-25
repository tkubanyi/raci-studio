"""Seed Global Payments Order-to-Cash reference process with intentional defects."""

from sqlalchemy.orm import Session

from app.models import (
    DIMENSION_LABELS,
    Activity,
    ActivityRole,
    Dimension,
    Process,
    Role,
    Workspace,
)


def seed_database(db: Session) -> None:
    if db.query(Workspace).first():
        return

    ws = Workspace(name="Global Payments — Prague SSC")
    db.add(ws)
    db.flush()

    dimensions = [
        Dimension(workspace_id=ws.id, slug="pdlc", name=DIMENSION_LABELS["pdlc"]),
        Dimension(workspace_id=ws.id, slug="ssc_ops", name=DIMENSION_LABELS["ssc_ops"]),
        Dimension(workspace_id=ws.id, slug="customer_jv", name=DIMENSION_LABELS["customer_jv"]),
    ]
    db.add_all(dimensions)
    db.flush()
    dim_map = {d.slug: d.id for d in dimensions}

    roles_data = [
        ("SSC Process Owner", "SSC Governance", 1.0, True),
        ("Order-to-Cash Lead", "Finance Operations", 1.0, True),
        ("Billing Analyst", "Finance Operations", 2.5, True),
        ("AR Specialist", "Finance Operations", 3.0, True),
        ("Credit Controller", "Finance Operations", 1.0, True),
        ("JV Business Partner", "Customer / JV", 0.5, True),
        ("Regional Controller", "Finance Operations", 0.0, False),
        ("IT Applications Support", "Technology", 0.5, True),
        ("Data Steward", "Data Governance", 1.0, True),
    ]
    roles: dict[str, Role] = {}
    for name, dept, fte, in_hris in roles_data:
        r = Role(workspace_id=ws.id, name=name, department=dept, fte=fte, in_hris=in_hris)
        db.add(r)
        roles[name] = r
    db.flush()

    otc = Process(
        workspace_id=ws.id,
        domain="Finance",
        name="Order-to-Cash (Reference)",
        description="Reference Order-to-Cash process for Prague SSC — includes intentional RACI defects for demo.",
        status="draft",
        version="1.0",
        owner_role_id=roles["Order-to-Cash Lead"].id,
    )
    db.add(otc)
    db.flush()

    activities_spec = [
        (1, "Receive customer order", True, "Order", "Validated order", "SAP", "4h", "Daily", [
            ("Billing Analyst", "R", "R", "I"),
            ("JV Business Partner", "I", "C", "A"),
        ]),
        (2, "Validate credit limit", False, "Customer master", "Credit decision", "SAP", None, "Per order", [
            ("Credit Controller", "R", "R", "C"),
        ]),
        # D-001 on PDLC: only R, no A — intentional gap in first dimension row above
        (3, "Generate invoice", False, "Validated order", "Invoice", "SAP", "24h", "Daily", [
            ("Billing Analyst", "R", "R", "I"),
            ("Order-to-Cash Lead", "A", "A", "I"),
            ("Credit Controller", "C", "A", "C"),
        ]),
        (4, "Post to GL", False, "Invoice", "GL posting", "SAP", "8h", "Daily", [
            ("AR Specialist", "R", "R", "I"),
            ("Regional Controller", "A", "A", "I"),
        ]),
        (5, "Apply cash receipt", False, "Bank file", "Cleared invoice", "SAP", "48h", "Daily", [
            ("AR Specialist", "R", "R", "I"),
            ("Billing Analyst", "R/A", "I", "I"),
        ]),
        (6, "Resolve billing dispute", False, "Dispute case", "Resolution", "ServiceNow", "5d", "Ad hoc", [
            ("JV Business Partner", "C", "C", "A"),
            ("Billing Analyst", "R", "R", "I"),
            ("Credit Controller", "C", "C", "C"),
        ]),
        (7, "Month-end O2C close", False, "Sub-ledger", "Closed period", "SAP", "3d", "Monthly", [
            ("Order-to-Cash Lead", "A", "A", "I"),
            ("SSC Process Owner", "C", "A", "I"),
            ("IT Applications Support", "R", "I", "I"),
        ]),
    ]

    act_objects: list[Activity] = []
    for seq, name, is_start, inputs, outputs, systems, sla, freq, raci_rows in activities_spec:
        pred = "" if is_start else str(act_objects[-1].id) if act_objects else ""
        act = Activity(
            process_id=otc.id,
            name=name,
            sequence=seq,
            inputs=inputs,
            outputs=outputs,
            systems=systems,
            sla=sla,
            frequency=freq,
            is_start=is_start,
            predecessor_ids=pred if act_objects else None,
        )
        db.add(act)
        act_objects.append(act)
    db.flush()

    slug_order = ("pdlc", "ssc_ops", "customer_jv")
    act_objects[1].predecessor_ids = None
    act_objects[4].predecessor_ids = f"{act_objects[3].id},{act_objects[2].id}"
    act_objects[5].predecessor_ids = str(act_objects[6].id)
    act_objects[6].predecessor_ids = str(act_objects[5].id)
    for act, (_, _, _, _, _, _, _, _, raci_rows) in zip(act_objects, activities_spec):
        for role_name, pdlc, ssc, cust in raci_rows:
            letters = {"pdlc": pdlc, "ssc_ops": ssc, "customer_jv": cust}
            for slug in slug_order:
                db.add(
                    ActivityRole(
                        activity_id=act.id,
                        role_id=roles[role_name].id,
                        dimension_id=dim_map[slug],
                        letters=letters[slug],
                    )
                )

    intake = Process(
        workspace_id=ws.id,
        domain="Operations",
        name="SSC Intake & Case Management",
        description="Lightweight second process for cross-process views.",
        status="draft",
        version="0.9",
        owner_role_id=roles["SSC Process Owner"].id,
    )
    db.add(intake)
    db.flush()
    a1 = Activity(
        process_id=intake.id,
        name="Log service request",
        sequence=1,
        is_start=True,
        inputs="Request",
        outputs="Ticket",
        systems="ServiceNow",
        sla="1h",
        frequency="Daily",
    )
    a2 = Activity(
        process_id=intake.id,
        name="Triage and assign",
        sequence=2,
        predecessor_ids=None,
        inputs="Ticket",
        outputs="Assigned ticket",
        systems="ServiceNow",
        sla="4h",
        frequency="Daily",
    )
    db.add_all([a1, a2])
    db.flush()
    a2.predecessor_ids = str(a1.id)
    for act, letters in [(a1, "R"), (a2, "R/A")]:
        for slug in slug_order:
            db.add(
                ActivityRole(
                    activity_id=act.id,
                    role_id=roles["SSC Process Owner"].id,
                    dimension_id=dim_map[slug],
                    letters=letters if slug == "ssc_ops" else "I",
                )
            )

    db.commit()
