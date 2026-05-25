# RACI Studio (Prototype)

**PR-RACI Studio** — process mapping, 3-D RACI matrices, and defect detection for the **Global Payments Prague SSC Transformation**, delivered by **PwC**.

Python **FastAPI** app with server-rendered UI (Jinja2), SQLite by default, deployable on **Render**.

## Features (prototype)

- Executive **Focus Areas** dashboard
- **Roles** registry (CRUD)
- **Processes** and **activities** (manual entry)
- **3-D RACI** views: PDLC, SSC Operations & RM, Customer/JV
- Rule-based **defect engine** (D-001 through D-012)
- **Mermaid** process diagrams
- **Document upload** (.txt, .md, .docx, .pdf, .xlsx) with text extraction; heuristic extraction by default, optional OpenAI when `OPENAI_API_KEY` is set
- Seed data: **Order-to-Cash** reference process with intentional defects

## Run locally (Windows)

```powershell
cd C:\Users\tkubanyi001\Projects\raci-studio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000

## Tests

```powershell
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Session/signing (set on Render) |
| `DATABASE_URL` | Default `sqlite:///./raci_studio.db`; use `sqlite:///./data/raci_studio.db` on Render |
| `OPENAI_API_KEY` | Optional LLM document extraction |
| `PORT` | Set by Render |

## Push to GitHub (manual — `gh` not required)

1. Create a new repository on GitHub (e.g. `raci-studio`), empty, no README.
2. In the project folder:

```powershell
cd C:\Users\tkubanyi001\Projects\raci-studio
git init
git add .
git commit -m "Initial RACI Studio prototype for Global Payments SSC"
git branch -M main
git remote add origin https://github.com/YOUR_ORG/raci-studio.git
git push -u origin main
```

Use GitHub Desktop or SSH remotes if you prefer.

## Deploy on Render

1. **New → Web Service** → connect your GitHub repo.
2. **Runtime:** Python 3.12
3. **Build command:** `pip install -r requirements.txt`
4. **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Environment:** add `SECRET_KEY` (generate), optional `OPENAI_API_KEY`
6. **Disk (optional):** add a persistent disk mounted at `/opt/render/project/src/data` and set  
   `DATABASE_URL=sqlite:///./data/raci_studio.db`  
   (free tier without disk resets SQLite on redeploy)
7. Deploy. Health check path: `/healthz`

Alternatively, use the included `render.yaml` with **Blueprint** deploy from the repo root.

## Project structure

```
raci-studio/
├── app/
│   ├── main.py           # Routes & app entry
│   ├── models.py         # SQLAlchemy models
│   ├── seed.py           # Global Payments seed data
│   ├── defects/engine.py # D-001–D-012 rules
│   ├── services/         # Ingestion, RACI, extraction
│   ├── templates/        # Jinja HTML
│   └── static/css/
├── tests/
├── requirements.txt
├── render.yaml
├── Procfile
└── README.md
```

## Disclaimer

Prototype for demonstration and workshop use. Not production-hardened (no SSO, virus scan, or full BRD scope). Review security before client-facing deployment.
