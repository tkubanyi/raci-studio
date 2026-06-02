# Run Presentation Studio locally (not exposed to the internet)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

.\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

$env:STREAMLIT_SERVER_ADDRESS = "127.0.0.1"
$env:STREAMLIT_SERVER_PORT = "8501"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

Write-Host "Opening Presentation Studio at http://127.0.0.1:8501"
streamlit run presentation_studio/app.py --server.address 127.0.0.1 --server.port 8501
