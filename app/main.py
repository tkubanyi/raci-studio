from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.config import BASE_DIR, get_settings
from app.database import get_db, init_db
from app.defects.engine import DefectEngine, Severity
from app.models import DIMENSION_LABELS, Activity, ActivityRole, Dimension, Document, Process, Role
from app.seed import seed_database
from app.services.extraction import heuristic_extract, llm_extract
from app.services.ingestion import extract_text_from_file
from app.services.raci import build_matrix, upsert_cell

settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

app = FastAPI(title=settings.app_title, version="1.0.0-prototype")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


def template_ctx(request: Request, **extra):
    return {
        "request": request,
        "settings": settings,
        "client": settings.client_name,
        "deliverer": settings.deliverer,
        "engagement": settings.engagement_name,
        "dimension_labels": DIMENSION_LABELS,
        **extra,
    }


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    processes = db.query(Process).all()
    roles = db.query(Role).all()
    dimensions = db.query(Dimension).all()
    engine = DefectEngine(role_overload_threshold=settings.role_overload_threshold)
    defects = engine.scan_workspace(processes, roles, dimensions)

    by_severity: dict[str, int] = {s.value: 0 for s in Severity}
    for d in defects:
        by_severity[d.severity.value] = by_severity.get(d.severity.value, 0) + 1

    process_density: dict[str, int] = {}
    for d in defects:
        key = d.process_name or "Unknown"
        process_density[key] = process_density.get(key, 0) + 1
    focus_processes = sorted(process_density.items(), key=lambda x: -x[1])[:10]

    processes_loaded = (
        db.query(Process)
        .options(joinedload(Process.activities).joinedload(Activity.assignments).joinedload(ActivityRole.role))
        .all()
    )
    role_load: dict[str, dict[str, int]] = {}
    for p in processes_loaded:
        for act in p.activities:
            for ar in act.assignments:
                rn = ar.role.name if ar.role else f"Role{ar.role_id}"
                if rn not in role_load:
                    role_load[rn] = {"R": 0, "A": 0, "C": 0, "I": 0}
                for letter in (ar.letters or "").upper():
                    if letter in role_load[rn]:
                        role_load[rn][letter] += 1

    overloaded = sorted(
        [(k, v["R"]) for k, v in role_load.items()],
        key=lambda x: -x[1],
    )[:10]

    return templates.TemplateResponse(
        "dashboard.html",
        template_ctx(
            request,
            processes=processes,
            roles_count=len(roles),
            defects_total=len(defects),
            by_severity=by_severity,
            focus_processes=focus_processes,
            overloaded_roles=overloaded,
            approved_pct=int(100 * sum(1 for p in processes if p.status == "published") / max(len(processes), 1)),
        ),
    )


@app.get("/roles", response_class=HTMLResponse)
def roles_list(request: Request, db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.name).all()
    return templates.TemplateResponse("roles.html", template_ctx(request, roles=roles))


@app.post("/roles")
def role_create(
    name: str = Form(...),
    department: str = Form(""),
    fte: float = Form(0.0),
    in_hris: str = Form("true"),
    db: Session = Depends(get_db),
):
    ws_id = db.query(Dimension).first().workspace_id
    db.add(
        Role(
            workspace_id=ws_id,
            name=name.strip(),
            department=department.strip() or None,
            fte=fte or None,
            in_hris=in_hris.lower() == "true",
        )
    )
    db.commit()
    return RedirectResponse("/roles", status_code=303)


@app.post("/roles/{role_id}/delete")
def role_delete(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).get(role_id)
    if role:
        db.delete(role)
        db.commit()
    return RedirectResponse("/roles", status_code=303)


@app.get("/processes", response_class=HTMLResponse)
def processes_list(request: Request, db: Session = Depends(get_db)):
    processes = db.query(Process).order_by(Process.name).all()
    return templates.TemplateResponse("processes.html", template_ctx(request, processes=processes))


@app.post("/processes")
def process_create(
    name: str = Form(...),
    domain: str = Form("Finance"),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    ws_id = db.query(Dimension).first().workspace_id
    db.add(Process(workspace_id=ws_id, name=name.strip(), domain=domain.strip(), description=description.strip() or None))
    db.commit()
    return RedirectResponse("/processes", status_code=303)


@app.get("/processes/{process_id}", response_class=HTMLResponse)
def process_detail(process_id: int, request: Request, db: Session = Depends(get_db)):
    process = (
        db.query(Process)
        .options(joinedload(Process.activities).joinedload(Activity.assignments))
        .filter(Process.id == process_id)
        .first()
    )
    roles = db.query(Role).order_by(Role.name).all()
    return templates.TemplateResponse(
        "process_detail.html",
        template_ctx(request, process=process, roles=roles),
    )


@app.post("/processes/{process_id}/activities")
def activity_create(
    process_id: int,
    name: str = Form(...),
    sequence: int = Form(0),
    is_start: str = Form("false"),
    sla: str = Form(""),
    frequency: str = Form(""),
    db: Session = Depends(get_db),
):
    db.add(
        Activity(
            process_id=process_id,
            name=name.strip(),
            sequence=sequence,
            is_start=is_start.lower() == "true",
            sla=sla.strip() or None,
            frequency=frequency.strip() or None,
        )
    )
    db.commit()
    return RedirectResponse(f"/processes/{process_id}", status_code=303)


@app.get("/processes/{process_id}/diagram", response_class=HTMLResponse)
def process_diagram(process_id: int, request: Request, db: Session = Depends(get_db)):
    process = db.query(Process).options(joinedload(Process.activities)).filter(Process.id == process_id).first()
    mermaid_lines = ["flowchart LR"]
    acts = sorted(process.activities, key=lambda a: a.sequence)
    for act in acts:
        node_id = f"A{act.id}"
        label = act.name.replace('"', "'")
        mermaid_lines.append(f'    {node_id}["{label}"]')
    for act in acts:
        if act.predecessor_ids:
            for pred in act.predecessor_ids.split(","):
                if pred.strip().isdigit():
                    mermaid_lines.append(f"    A{pred.strip()} --> A{act.id}")
    if len(acts) == 1:
        mermaid_lines.append(f"    Start([Start]) --> A{acts[0].id}")
    mermaid = "\n".join(mermaid_lines)
    return templates.TemplateResponse(
        "diagram.html",
        template_ctx(request, process=process, mermaid=mermaid),
    )


@app.get("/raci/{process_id}", response_class=HTMLResponse)
def raci_view(
    process_id: int,
    request: Request,
    dimension: str = "ssc_ops",
    db: Session = Depends(get_db),
):
    matrix = build_matrix(db, process_id, dimension)
    dimensions = db.query(Dimension).all()
    engine = DefectEngine(role_overload_threshold=settings.role_overload_threshold)
    defects = []
    if matrix["process"] and matrix["dimension"]:
        defects = engine.scan_process(
            matrix["process"],
            matrix["roles"],
            matrix["dimension"].id,
            matrix["dimension"].slug,
        )
    defect_cells: set[str] = set()
    for d in defects:
        if d.activity_id and d.role_id:
            defect_cells.add(f"{d.activity_id}:{d.role_id}")

    return templates.TemplateResponse(
        "raci.html",
        template_ctx(
            request,
            matrix=matrix,
            dimensions=dimensions,
            current_dimension=dimension,
            defects=defects,
            defect_cells=defect_cells,
        ),
    )


@app.post("/raci/{process_id}/cell")
def raci_cell_update(
    process_id: int,
    activity_id: int = Form(...),
    role_id: int = Form(...),
    dimension_id: int = Form(...),
    letters: str = Form(""),
    dimension: str = Form("ssc_ops"),
    db: Session = Depends(get_db),
):
    upsert_cell(db, activity_id, role_id, dimension_id, letters)
    return RedirectResponse(f"/raci/{process_id}?dimension={dimension}", status_code=303)


@app.get("/defects", response_class=HTMLResponse)
def defects_view(
    request: Request,
    dimension: str = "",
    severity: str = "",
    db: Session = Depends(get_db),
):
    processes = db.query(Process).options(joinedload(Process.activities).joinedload(Activity.assignments)).all()
    roles = db.query(Role).all()
    dimensions = db.query(Dimension).all()
    engine = DefectEngine(role_overload_threshold=settings.role_overload_threshold)
    defects = engine.scan_workspace(processes, roles, dimensions)
    if dimension:
        defects = [d for d in defects if d.dimension_slug == dimension]
    if severity:
        defects = [d for d in defects if d.severity.value == severity]
    return templates.TemplateResponse(
        "defects.html",
        template_ctx(request, defects=defects, dimensions=dimensions, filter_dimension=dimension, filter_severity=severity),
    )


@app.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    return templates.TemplateResponse(
        "documents.html",
        template_ctx(request, documents=docs, has_llm=settings.has_llm),
    )


@app.post("/documents/upload")
async def document_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ws_id = db.query(Dimension).first().workspace_id
    dest = settings.upload_dir / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        text = extract_text_from_file(dest, file.filename)
    except Exception as exc:
        text = f"[Extraction error: {exc}]"
    try:
        result = await llm_extract(text)
    except Exception:
        result = heuristic_extract(text)
    summary = json.dumps({"mode": result.mode, "processes": len(result.processes), "roles": len(result.roles)}, indent=2)
    doc = Document(
        workspace_id=ws_id,
        filename=file.filename,
        mime_type=file.content_type,
        storage_path=str(dest),
        extracted_text=text[:50000],
        status="extracted",
        extraction_summary=summary,
    )
    db.add(doc)
    db.commit()
    return RedirectResponse("/documents", status_code=303)


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_detail(doc_id: int, request: Request, db: Session = Depends(get_db)):
    doc = db.query(Document).get(doc_id)
    extraction = {}
    if doc and doc.extraction_summary:
        try:
            extraction = json.loads(doc.extraction_summary)
        except json.JSONDecodeError:
            extraction = {"raw": doc.extraction_summary}
    preview = (doc.extracted_text or "")[:4000] if doc else ""
    return templates.TemplateResponse(
        "document_detail.html",
        template_ctx(request, document=doc, preview=preview, extraction=extraction),
    )


@app.get("/raci/{process_id}/export.csv")
def export_raci_csv(
    process_id: int,
    dimension: str = "ssc_ops",
    db: Session = Depends(get_db),
):
    import csv
    import io

    matrix = build_matrix(db, process_id, dimension)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Activity"] + [r.name for r in matrix["roles"]])
    for act in matrix["activities"]:
        row = [act.name]
        for role in matrix["roles"]:
            row.append(matrix["cells"].get(f"{act.id}:{role.id}", ""))
        writer.writerow(row)
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="raci_{process_id}_{dimension}.csv"'},
    )


@app.get("/raci/{process_id}/export.json")
def export_raci_json(
    process_id: int,
    dimension: str = "ssc_ops",
    db: Session = Depends(get_db),
):
    matrix = build_matrix(db, process_id, dimension)
    engine = DefectEngine(role_overload_threshold=settings.role_overload_threshold)
    defects = []
    if matrix["process"] and matrix["dimension"]:
        defects = engine.scan_process(
            matrix["process"],
            matrix["roles"],
            matrix["dimension"].id,
            matrix["dimension"].slug,
        )
    payload = {
        "process": matrix["process"].name if matrix["process"] else "",
        "dimension": matrix["dimension"].name if matrix["dimension"] else dimension,
        "rows": [
            {
                "activity": act.name,
                "cells": {
                    r.name: matrix["cells"].get(f"{act.id}:{r.id}", "")
                    for r in matrix["roles"]
                },
            }
            for act in matrix["activities"]
        ],
        "defects": [
            {
                "rule_id": d.rule_id,
                "severity": d.severity.value,
                "message": d.message,
                "activity_id": d.activity_id,
                "role_id": d.role_id,
            }
            for d in defects
        ],
    }
    return JSONResponse(payload)


@app.get("/api/defects/{process_id}")
def api_defects(process_id: int, dimension: str = "ssc_ops", db: Session = Depends(get_db)):
    process = db.query(Process).options(joinedload(Process.activities).joinedload(Activity.assignments)).get(process_id)
    dim = db.query(Dimension).filter_by(slug=dimension).first()
    roles = db.query(Role).all()
    engine = DefectEngine(role_overload_threshold=settings.role_overload_threshold)
    defects = engine.scan_process(process, roles, dim.id, dim.slug) if process and dim else []
    return [
        {
            "rule_id": d.rule_id,
            "severity": d.severity.value,
            "message": d.message,
            "activity_id": d.activity_id,
            "role_id": d.role_id,
        }
        for d in defects
    ]
