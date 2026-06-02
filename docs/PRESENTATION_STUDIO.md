# Presentation Studio

Local Python app to build **PwC brand-formatted PowerPoint** decks (15-slide discovery layout) from:

- **Word** (`.docx`)
- **PDF** (`.pdf`)
- **Plain text** (paste in the UI)

Includes an **AI assistant** tab to refine content and optionally specify **where to save** the `.pptx` on your machine.

## Requirements

- Python 3.11+ (locally installed)
- Dependencies from `requirements.txt` (includes `streamlit`, `python-pptx`, `python-docx`, `pdfplumber`)
- Optional: `OPENAI_API_KEY` in `.env` for AI edits

## Run locally (not on the internet)

From the repo root:

```powershell
.\scripts\run_presentation_studio.ps1
```

Or manually:

```powershell
cd C:\Users\tkubanyi001\Projects\raci-studio
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run presentation_studio/app.py --server.address 127.0.0.1 --server.port 8501
```

Open **http://127.0.0.1:8501** in your browser. The app binds to localhost only.

## Workflow

1. **Source content** — upload `.docx`/`.pdf` or paste text; click **Parse**.
2. **Generate deck** — click **Generate**; download the file or read the saved path.
3. **AI assistant** — e.g. *"Add a fourth opportunity about data quality and save to `C:\...\deck_v2.pptx`"*.

## Configuration (`.env` or sidebar)

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | AI content edits |
| `OPENAI_MODEL` | Default `gpt-4o-mini` |

Sidebar overrides:

- Brand template `.pptx` (default: repo `data/presentation-templates/Project_Vienna_Discovery_Phase.pptx`)
- Brand JSON tokens (`graphic_elements_correct.brand.summary.json`)
- Default output folder (`presentation_studio_outputs/`)

For full brand icon galleries, point **Brand template** to your PwC `Graphic elements_correct.pptx` on OneDrive.

## GitHub

Push this repo to GitHub for version control. **Do not** deploy Streamlit to a public host unless you add authentication — this tool is intended for **local use** on your laptop.

## CLI (Vienna sample)

```powershell
python scripts/generate_vienna_brand_deck.py
```

Uses paths configured in that script for the Global Payments Vienna document.

## Architecture

```
presentation_studio/
  app.py              # Streamlit UI
  content_parser.py   # docx / pdf / text → structured doc dict
  deck_builder.py     # doc dict → 15-slide brand PPTX
  ai_coach.py         # OpenAI JSON patches + save path
  config.py           # paths and settings
```
