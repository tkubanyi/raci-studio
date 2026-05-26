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
from app.services.ai import extract_processes_from_document
from app.services.diagram import (
    diagram_from_process,
    parse_diagram_json,
    render_mermaid_swimlane,
)
from app.services.extraction import heuristic_extract
from app.services.ingestion import SUPPORTED_EXTENSIONS, ingest_file
from app.services.process_import import (
    delete_document,
    delete_process,
    extraction_summary_payload,
    import_from_extraction,
)
from app.services.raci import build_matrix, upsert_cell

settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.cache_size = 0

app = FastAPI(title=settings.app_title, version="1.0.0-prototype")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


def template_ctx(request: Request, **extra):
    return {
        "request": request,
        "client": settings.client_name,
        "deliverer": settings.deliverer,
        "engagement": settings.engagement_name,
        "dimension_labels": DIMENSION_LABELS,
        **extra,
    }


@app.on_event("startup")
def on_startup() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
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
        request,
        "dashboard.html",
        template_ctx(
            request,
            processes=processes,
            roles_count=len(roles),
            defects_total=len(defects),
            by_severity_items=list(by_severity.items()),
            focus_processes=focus_processes,
            overloaded_roles=overloaded,
            approved_pct=int(100 * sum(1 for p in processes if p.status == "published") / max(len(processes), 1)),
        ),
    )


@app.get("/roles", response_class=HTMLResponse)
def roles_list(request: Request, db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.name).all()
    return templates.TemplateResponse(request, "roles.html", template_ctx(request, roles=roles))


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
def processes_list(request: Request, db: Session = Depends(get_db), msg: str = ""):
    processes = db.query(Process).order_by(Process.name).all()
    return templates.TemplateResponse(
        request,
        "processes.html",
        template_ctx(request, processes=processes, flash_message=msg),
    )


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


@app.post("/processes/{process_id}/delete")
def process_delete(process_id: int, db: Session = Depends(get_db)):
    delete_process(db, process_id)
    return RedirectResponse("/processes?msg=Process+deleted", status_code=303)


@app.get("/processes/{process_id}", response_class=HTMLResponse)
def process_detail(process_id: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    process = (
        db.query(Process)
        .options(joinedload(Process.activities).joinedload(Activity.assignments))
        .filter(Process.id == process_id)
        .first()
    )
    roles = db.query(Role).order_by(Role.name).all()
    return templates.TemplateResponse(
        request,
        "process_detail.html",
        template_ctx(request, process=process, roles=roles, flash_message=msg),
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
    process = (
        db.query(Process)
        .options(joinedload(Process.activities).joinedload(Activity.assignments).joinedload(ActivityRole.role))
        .filter(Process.id == process_id)
        .first()
    )
    if not process:
        return RedirectResponse("/processes", status_code=303)

    diagram = parse_diagram_json(process.diagram_json)
    acts = sorted(process.activities, key=lambda a: a.sequence)
    if not diagram or not diagram.get("nodes"):
        diagram = diagram_from_process(process, acts)

    mermaid = render_mermaid_swimlane(diagram)
    return templates.TemplateResponse(
        request,
        "diagram.html",
        template_ctx(
            request,
            process=process,
            mermaid=mermaid,
            diagram=diagram,
            activities=acts,
        ),
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
        request,
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
        request,
        "defects.html",
        template_ctx(request, defects=defects, dimensions=dimensions, filter_dimension=dimension, filter_severity=severity),
    )


@app.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: Session = Depends(get_db), msg: str = ""):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    process_names = {p.id: p.name for p in db.query(Process).all()}
    doc_rows: list[dict] = []
    for doc in docs:
        linked: list[tuple[int, str]] = []
        if doc.extraction_summary:
            try:
                payload = json.loads(doc.extraction_summary)
                for pid in payload.get("created_process_ids") or []:
                    if pid in process_names:
                        linked.append((pid, process_names[pid]))
            except json.JSONDecodeError:
                pass
        doc_rows.append({"doc": doc, "linked": linked})
    return templates.TemplateResponse(
        request,
        "documents.html",
        template_ctx(
            request,
            doc_rows=doc_rows,
            has_llm=settings.has_llm,
            vision_model=settings.openai_vision_model,
            supported_extensions=", ".join(sorted(SUPPORTED_EXTENSIONS)),
            flash_message=msg,
        ),
    )


@app.post("/documents/upload")
async def document_upload(
    file: UploadFile = File(...),
    domain: str = Form("Finance"),
    db: Session = Depends(get_db),
):
    ws_id = db.query(Dimension).first().workspace_id
    safe_name = Path(file.filename or "upload.txt").name
    dest = settings.upload_dir / safe_name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        ingestion = ingest_file(dest, safe_name)
        result = await extract_processes_from_document(ingestion, filename=safe_name)
        text = ingestion.text
    except Exception as exc:
        text = f"[Ingestion error: {exc}]"
        result = heuristic_extract(text, filename=safe_name)

    doc = Document(
        workspace_id=ws_id,
        filename=safe_name,
        mime_type=file.content_type,
        storage_path=str(dest),
        extracted_text=text[:50000],
        status="processing",
        extraction_summary=None,
    )
    db.add(doc)
    db.flush()

    created_ids: list[int] = []
    import_error: str | None = None
    try:
        created_ids = import_from_extraction(
            db,
            ws_id,
            result,
            source_filename=safe_name,
            document_id=doc.id,
            domain=domain.strip() or "Finance",
        )
        doc.status = "imported" if created_ids else "extracted"
    except Exception as exc:
        import_error = str(exc)
        doc.status = "extracted"

    summary = extraction_summary_payload(result, created_ids)
    if import_error:
        summary["import_error"] = import_error
    doc.extraction_summary = json.dumps(summary, indent=2)
    db.commit()

    if created_ids:
        first = created_ids[0]
        msg = f"Created+{len(created_ids)}+process(es)+from+SOP"
        if len(created_ids) == 1:
            return RedirectResponse(f"/processes/{first}?msg={msg}", status_code=303)
        return RedirectResponse(f"/processes?msg={msg}", status_code=303)
    return RedirectResponse("/documents?msg=Document+saved+but+no+process+steps+detected", status_code=303)


@app.post("/documents/{doc_id}/delete")
def document_delete(doc_id: int, db: Session = Depends(get_db)):
    delete_document(db, doc_id)
    return RedirectResponse("/documents?msg=Document+deleted", status_code=303)


@app.post("/documents/{doc_id}/build-processes")
async def document_build_processes(
    doc_id: int,
    domain: str = Form("Finance"),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).get(doc_id)
    if not doc:
        return RedirectResponse("/documents?msg=Document+not+found", status_code=303)
    if not doc.extracted_text:
        return RedirectResponse(f"/documents/{doc_id}?msg=No+extracted+text", status_code=303)

    from app.services.ingestion_types import IngestionResult

    ingestion = IngestionResult(
        text=doc.extracted_text,
        source_type="text",
        filename=doc.filename,
    )
    result = await extract_processes_from_document(ingestion, filename=doc.filename)

    created_ids = import_from_extraction(
        db,
        doc.workspace_id,
        result,
        source_filename=doc.filename,
        document_id=doc.id,
        domain=domain.strip() or "Finance",
    )
    existing = []
    if doc.extraction_summary:
        try:
            existing = json.loads(doc.extraction_summary).get("created_process_ids", [])
        except json.JSONDecodeError:
            pass
    summary = extraction_summary_payload(result, existing + created_ids)
    doc.extraction_summary = json.dumps(summary, indent=2)
    doc.status = "imported" if created_ids else doc.status
    db.commit()
    return RedirectResponse(f"/processes?msg=Created+{len(created_ids)}+process(es)", status_code=303)


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_detail(doc_id: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    doc = db.query(Document).get(doc_id)
    extraction: dict = {}
    linked_processes: list[Process] = []
    if doc and doc.extraction_summary:
        try:
            extraction = json.loads(doc.extraction_summary)
            ids = extraction.get("created_process_ids") or []
            if ids:
                linked_processes = db.query(Process).filter(Process.id.in_(ids)).all()
        except json.JSONDecodeError:
            extraction = {"raw": doc.extraction_summary}
    preview = (doc.extracted_text or "")[:4000] if doc else ""
    return templates.TemplateResponse(
        request,
        "document_detail.html",
        template_ctx(
            request,
            document=doc,
            preview=preview,
            extraction=extraction,
            linked_processes=linked_processes,
            flash_message=msg,
        ),
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
