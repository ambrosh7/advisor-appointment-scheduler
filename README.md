# Advisor Appointment Scheduler

Voice-first advisor appointment booking: FastAPI Orchestrator + browser voice console (STT/TTS).

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI · Uvicorn · Orchestrator (`src/`) |
| UI | Static voice console (`web/`) |
| Production | **Railway** (API) + **Vercel** (UI) |

Full steps: [`deployment-plan.md`](./deployment-plan.md) · [`docs/deploy-railway-vercel.md`](./docs/deploy-railway-vercel.md)

## Local

```bash
cd "/Users/apple/Desktop/Voice Agent"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill secrets
PYTHONPATH=src python3 -m api.chat
# → http://127.0.0.1:8000/
```

Leave `web/config.js` `AAS_API_BASE` empty for same-origin local use.

## Deploy (Railway + Vercel)

1. **Push** this repo to GitHub (never commit `.env` or Google credential files).
2. **Railway** — deploy from GitHub (uses `Dockerfile` + `railway.toml`).
   - Set variables from `.env.example` (`GEMINI_*`, `GOOGLE_*`, `MCP_*`, `APP_ENV=production`, etc.).
   - Generate a public domain; confirm `GET /health` → `"status":"ok"`.
3. **Vercel** — import the same repo.
   - Framework: **Other** (not FastAPI)
   - Env: `AAS_API_BASE=https://<your-service>.up.railway.app`
   - Root `vercel.json` builds/serves `web/` (static only; API stays on Railway)
4. **Railway** — set `CORS_ORIGINS=https://<your-project>.vercel.app`
5. Open the Vercel URL and smoke: Acknowledge → Name → Book → Confirm.

Optional Vapi custom-LLM base URL: `https://<railway-host>/v1`

## Docker (Railway parity)

```bash
docker build -t advisor-aas .
docker run --rm -p 8000:8000 --env-file .env advisor-aas
```
