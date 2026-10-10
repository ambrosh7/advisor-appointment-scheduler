# Deploy: Railway (API) + Vercel (voice UI)

Split hosting for this stack:

| Host | Role |
|------|------|
| **Railway** | FastAPI + Orchestrator (`Dockerfile` + `railway.toml`) |
| **Vercel** | Static voice console (`web/`) |

Local and single-host Railway still work: leave `AAS_API_BASE` empty so the UI calls the same origin.

Canonical checklist: [`../deployment-plan.md`](../deployment-plan.md)

## 1. Railway — backend

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
2. Select this repo — Railway uses `Dockerfile` / `railway.toml`
3. **Variables** (same secrets as local `.env`):

| Key | Notes |
|-----|--------|
| `GEMINI_API_KEY` | Required |
| `GEMINI_MODEL` | Prefer a model with quota headroom |
| `GOOGLE_CALENDAR_ID` | Usually `primary` |
| `GOOGLE_DOCS_PREBOOKING_ID` | Docs ID |
| `GOOGLE_GMAIL_ADVISOR_TO` | Advisor inbox |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full SA JSON as one string |
| `MCP_SERVER_URL` | MCP HTTP URL |
| `MCP_HTTP_BEARER_TOKEN` | MCP bearer |
| `SECURE_LINK_TEMPLATE` | `https://…/complete?ref={code}` |
| `ADVICE_EDUCATIONAL_URL` | Optional |
| `APP_ENV` | `production` |
| `CORS_ORIGINS` | Vercel origin(s), e.g. `https://your-app.vercel.app` |

4. Generate a public domain (`*.up.railway.app`)
5. Check `https://<railway-host>/health` → `"status":"ok"`

Optional: open `https://<railway-host>/` — container also serves `web/`. Prefer Vercel for the public demo URL.

## 2. Point the UI at Railway

On Vercel → **Environment Variables**:

```text
AAS_API_BASE=https://<your-service>.up.railway.app
```

Build runs `web/package.json` → `npm run build` → `inject-api-base.js` writes `config.js`.

Manual override (local or commit): see `web/config.example.js`.

## 3. Vercel — frontend

1. [vercel.com](https://vercel.com) → **Add New** → **Project** → import the same GitHub repo
2. Framework Preset: **Other** (not FastAPI — backend is Railway)
3. Root Directory: repo root (uses root `vercel.json`) **or** `web`
4. Ensure `AAS_API_BASE` is set (Production + Preview if needed)
5. Deploy

Root `vercel.json` + `.vercelignore` keep Vercel from auto-detecting the FastAPI apps under `src/api/`. `/static/*` rewrites map to files in `web/`.

## 4. Verify

1. Open the Vercel URL → voice console loads
2. Start a session (Acknowledge → name → book → confirm)
3. If the UI fails to connect: confirm `AAS_API_BASE`, Railway `/health`, and `CORS_ORIGINS` (exact `https://` origin)

## 5. Vapi (optional)

Custom-LLM base URL on Railway: `https://<railway-host>/v1`

## Free-tier notes

- Railway: cold starts / credit limits on hobby usage; card may be required for verification
- Vercel: static hosting is free for this UI
- In-memory sessions reset when Railway restarts (expected for this demo)
