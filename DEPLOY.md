# Deploy RACI Studio to Render (internet URL)

## Step 1 — Create GitHub repository

1. Open https://github.com/new
2. **Repository name:** `raci-studio` (or your choice)
3. **Visibility:** Private (recommended) or Public
4. Leave **empty** — do not add README, .gitignore, or license
5. Click **Create repository**

## Step 2 — Push code from your PC

Replace `YOUR_GITHUB_USERNAME` with your GitHub username.

```powershell
cd C:\Users\tkubanyi001\Projects\raci-studio
git branch -M main
git remote remove origin 2>$null
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/raci-studio.git
git push -u origin main
```

Git may open a browser to sign in (GitHub credential manager). Use your work or personal GitHub account.

## Step 3 — Create Render web service

1. Sign in at https://dashboard.render.com
2. Click **New +** → **Blueprint**
3. Connect your **GitHub** account if prompted (Render → Account Settings → GitHub)
4. Select the **`raci-studio`** repository
5. Render reads `render.yaml` and creates **raci-studio** web service
6. Click **Apply** / **Deploy Blueprint**

**Or manual web service (if Blueprint is unavailable):**

1. **New +** → **Web Service**
2. Connect repo `raci-studio`, branch `main`
3. **Runtime:** Python 3
4. **Build command:** `pip install -r requirements.txt`
5. **Start command:** `mkdir -p data uploads && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. **Health check path:** `/healthz`
7. **Environment variables:**
   - `PYTHON_VERSION` = `3.12.7`
   - `SECRET_KEY` = (Generate)
   - `DATABASE_URL` = `sqlite:///./data/raci_studio.db`
8. **Instance type:** Free
9. Click **Create Web Service**

## Step 4 — Your public URL

After the first deploy succeeds (5–10 minutes), open:

`https://raci-studio.onrender.com`

(Exact host is shown on the service page — often `raci-studio-xxxx.onrender.com`.)

## Notes

- **Free tier:** App sleeps after ~15 min idle; first request may take ~30s to wake.
- **SQLite:** Data resets on redeploy unless you add a Render **persistent disk** mounted at `data/`.
- **Optional:** Add `OPENAI_API_KEY` in Render → Environment for LLM document extraction.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Build fails on Python version | Set `PYTHON_VERSION=3.12.7` in Environment |
| 502 on startup | Check Logs; confirm start command matches above |
| Empty app / no seed data | Wait for deploy to finish; visit `/` once |
