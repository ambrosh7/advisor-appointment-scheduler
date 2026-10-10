# Deploy on Render (FastAPI + voice console)

This is the recommended host for the current stack: **Uvicorn + Orchestrator + `web/` UI**.

## What gets deployed

| Path | Role |
|------|------|
| `GET /` | Latest voice-console frontend |
| `POST /session`, `/session/{id}/message` | Booking API |
| `POST /v1/chat/completions` | Vapi custom-LLM (optional) |
| `GET /health` | Render health check |

## 1. Push the repo to GitHub

```bash
cd "/Users/apple/Desktop/Voice Agent"
git init
git add Dockerfile render.yaml requirements.txt src web docs pyproject.toml setup.cfg .gitignore .env.example deployment-plan.md
git commit -m "Add Render Docker deploy for voice agent"
# Create a GitHub repo, then:
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Do **not** commit `.env`, `credentials.json`, `token.json`, or service-account JSON.

## 2. Create the Render web service

**Option A — Blueprint (preferred)**  
1. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**  
2. Connect the GitHub repo  
3. Render reads `render.yaml` and creates `advisor-appointment-scheduler`

**Option B — Manual**  
1. **New** → **Web Service** → connect repo  
2. Runtime: **Docker** (uses `Dockerfile`)  
3. Health check path: `/health`  
4. Instance: Free or Starter  

## 3. Set environment variables

In the service → **Environment**:

| Key | Notes |
|-----|--------|
| `GEMINI_API_KEY` | Required |
| `GEMINI_MODEL` | e.g. `gemini-2.5-flash` (avoid exhausted free-tier IDs) |
| `GOOGLE_CALENDAR_ID` | Usually `primary` or a shared calendar ID |
| `GOOGLE_DOCS_PREBOOKING_ID` | Docs ID for pre-booking notes |
| `GOOGLE_GMAIL_ADVISOR_TO` | Advisor inbox for drafts |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full service-account JSON **as one secret string** |
| `MCP_SERVER_URL` | Railway MCP URL |
| `MCP_HTTP_BEARER_TOKEN` | MCP bearer |
| `SECURE_LINK_TEMPLATE` | `https://…/complete?ref={code}` |
| `APP_ENV` | `production` |

Share the Calendar (and Docs if local) with the service-account email as **Editor**.

OAuth `credentials.json` / `token.json` are for local only — use the service account on Render.

## 4. Deploy & verify

1. Trigger deploy; wait until live  
2. Open `https://<service>.onrender.com/` — voice console  
3. `curl https://<service>.onrender.com/health` → `"status":"ok"`  
4. Smoke: Acknowledge → full name → book → confirm  
5. Optional Vapi: custom LLM base URL `https://<service>.onrender.com/v1`

## 5. Free-tier notes

- Cold starts after idle (~15s–1m)  
- Ephemeral disk — never rely on writing OAuth tokens  
- In-memory sessions reset on restart (expected for this demo architecture)

## Local Docker parity

```bash
docker build -t advisor-aas .
docker run --rm -p 8000:8000 --env-file .env \
  -e GOOGLE_SERVICE_ACCOUNT_FILE=/secrets/sa.json \
  -v "$PWD/service-account.json:/secrets/sa.json:ro" \
  advisor-aas
```
