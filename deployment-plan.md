# Deployment plan — Advisor Appointment Scheduler

**Hosts:** Railway (backend API) + Vercel (Holdroom voice UI)  
**Repo:** `https://github.com/ambrosh7/advisor-appointment-scheduler` (or your fork)  
**Public demo:** https://advisor-appointment-scheduler-pd5t-eight.vercel.app  
**Detail companion:** [`docs/deploy-railway-vercel.md`](./docs/deploy-railway-vercel.md)

This plan deploys the **entire product**: FastAPI Orchestrator (booking brain, Google/MCP, optional Vapi) **and** the Holdroom voice console in `web/`.

---

## 1. Architecture

```text
┌──────────────────────────────┐         HTTPS          ┌──────────────────────────────┐
│  Vercel (static)             │  ───────────────────►  │  Railway (Docker)            │
│  Root: web/                  │   /session, /message   │  Dockerfile + railway.toml   │
│                              │                        │                              │
│  index.html                  │                        │  uvicorn api.chat.app:app    │
│  styles.css · app.js         │                        │  Orchestrator + side effects │
│  config.js → AAS_API_BASE    │                        │  Gemini · Calendar · MCP     │
│  vercel.json (/static rewrite)                        │  GET /health · POST /v1/...  │
└──────────────────────────────┘                        └──────────────────────────────┘
         Public demo URL                                         API / Vapi URL
```

| Piece | Host | Source |
|-------|------|--------|
| Latest frontend (voice console) | **Vercel** | `web/` (`index.html`, `styles.css`, `app.js`, `config.js`) |
| Backend API + Orchestrator | **Railway** | `src/` via `Dockerfile` |
| Optional phone / WebRTC (Vapi) | Points at Railway | `POST /v1/chat/completions` |

Railway can also serve `GET /` + `/static/*` from the same container (useful as a fallback). Prefer **Vercel** as the public demo URL so the UI and API scale independently.

---

## 2. What ships where

### Backend (Railway)

| Path | Role |
|------|------|
| `POST /session` | Create booking session |
| `POST /session/{id}/message` | User turn → Orchestrator |
| `GET /session/{id}` | Debug state |
| `GET /health` | Health / deploy check |
| `GET /voice/config` | Public voice client hints |
| `POST /v1/chat/completions` | Vapi custom-LLM (optional) |
| `GET /`, `/static/*` | Same UI if opened on Railway |

### Frontend (Vercel) — latest console

| File | Role |
|------|------|
| `web/index.html` | Product shell, stage, chips, turn history |
| `web/styles.css` | Atmosphere, stage, motions |
| `web/app.js` | Session API client, STT/TTS, stepper, quick replies |
| `web/config.js` | `window.AAS_API_BASE` → Railway public URL |
| `web/vercel.json` | Maps `/static/*` → files in `web/` |

Local / same-origin: leave `AAS_API_BASE` empty. Cross-origin (Vercel → Railway): set the Railway HTTPS origin.

---

## 3. Prerequisites

1. GitHub repo with latest `main` (includes `web/`, `Dockerfile`, `railway.toml`, `web/vercel.json`).
2. Accounts: [Railway](https://railway.app), [Vercel](https://vercel.com) (GitHub OAuth).
3. Secrets ready (from local `.env` — **never commit** `.env` / OAuth tokens / SA files):
   - `GEMINI_API_KEY`, `GEMINI_MODEL`
   - Google Calendar / Docs / Gmail targets
   - `GOOGLE_SERVICE_ACCOUNT_JSON` (full JSON string)
   - `MCP_SERVER_URL`, `MCP_HTTP_BEARER_TOKEN`
   - `SECURE_LINK_TEMPLATE`, `APP_ENV=production`
4. Calendar (and Docs if needed) shared with the **service-account email** as Editor.
5. Browser for smoke: Chrome or Edge (Web Speech STT).

---

## 4. Deploy order (do in sequence)

### Phase 1 — Push code

```bash
cd "/Users/apple/Desktop/Voice Agent"
git status
# commit deploy files if needed, then:
git push origin main
```

Do **not** commit: `.env`, `credentials.json`, `token.json`, service-account JSON files.

### Phase 2 — Railway (backend first)

1. Railway → **New Project** → **Deploy from GitHub** → select this repo.
2. Confirm build uses **Dockerfile** (`railway.toml` sets `DOCKERFILE` + `healthcheckPath=/health`).
3. **Variables** → add:

| Variable | Notes |
|----------|--------|
| `GEMINI_API_KEY` | Required |
| `GEMINI_MODEL` | Prefer a model with quota headroom (avoid exhausted free-tier IDs) |
| `GOOGLE_CALENDAR_ID` | Usually `primary` or shared calendar ID |
| `GOOGLE_DOCS_PREBOOKING_ID` | Pre-booking Doc ID |
| `GOOGLE_GMAIL_ADVISOR_TO` | Advisor inbox for drafts |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Entire SA JSON as one line/string |
| `MCP_SERVER_URL` | MCP HTTP endpoint |
| `MCP_HTTP_BEARER_TOKEN` | MCP bearer |
| `SECURE_LINK_TEMPLATE` | `https://…/complete?ref={code}` |
| `ADVICE_EDUCATIONAL_URL` | Optional educational link |
| `APP_ENV` | `production` |
| `CORS_ORIGINS` | Set after Vercel exists (Phase 4); temporarily `*` for first API smoke |

4. **Settings** → generate public domain → note  
   `https://<service>.up.railway.app`
5. Verify:

```bash
curl -sS "https://<service>.up.railway.app/health"
# expect: "status":"ok"
```

6. Optional smoke of API-only UI: open the Railway URL (serves latest `web/` from the image).

### Phase 3 — Wire frontend → Railway

Preferred (no hardcoded URL in git): on **Vercel → Project → Settings → Environment Variables** set:

```text
AAS_API_BASE=https://<service>.up.railway.app
```

At build time, `web/package.json` → `npm run build` runs `inject-api-base.js` and writes `web/config.js`.

Alternative: commit a filled `web/config.js` (see `web/config.example.js`).

`web/app.js` prefixes `/session` and `/session/{id}/message` with `window.AAS_API_BASE`.

### Phase 4 — Vercel (latest frontend)

1. Vercel → **Add New** → **Project** → import the **same** GitHub repo.
2. Configure (repo-root deploy is OK — `vercel.json` + `.vercelignore` force static `web/`):

| Setting | Value |
|---------|--------|
| **Root Directory** | `.` (repo root) **or** `web` |
| **Framework Preset** | **Other** (do **not** pick FastAPI — API is on Railway) |
| **Build Command** | From root `vercel.json`: `npm run build --prefix web` |
| **Output Directory** | `web` |
| **Env** | `AAS_API_BASE` = Railway HTTPS origin |

If Vercel errors with “No FastAPI entrypoint” / dual `chat`+`voice` apps: set Framework to **Other**, ensure Root Directory is not forcing Python, Redeploy. Do **not** add `[tool.vercel] entrypoint` in `pyproject.toml` (that would host the API on Vercel).

3. Deploy → note `https://<project>.vercel.app` (or custom domain).
4. Back on Railway, set:

```text
CORS_ORIGINS=https://<project>.vercel.app
```

Add preview URLs too if you use them (comma-separated). Redeploy Railway if variables do not hot-reload.

### Phase 5 — End-to-end verification

1. Open the **Vercel** URL (primary demo).
2. Hard-refresh; allow microphone; enable **TTS** once (gesture unlock).
3. Flow:
   - Acknowledge (“yes” / “I understand”)
   - **Full name**
   - Book new → **KYC Onboarding** or **SIP Mandates**
   - Time preference → pick slot → confirm
4. Confirm Calendar event includes **customer name** + booking code; Docs/Gmail side effects as configured.
5. If the UI cannot start a session: check `AAS_API_BASE`, Railway `/health`, and `CORS_ORIGINS` (exact `https://` origin).

### Phase 6 — Optional voice transport (ElevenLabs / Vapi)

For an [ElevenLabs-style continuous voice agent](https://join.elevenlabs.io/api/conversational-ai), see `docs/elevenlabs-setup.md`:

1. Create a Conversational AI agent
2. Point custom LLM at Railway `https://<host>/v1`
3. Set `ELEVENLABS_AGENT_ID` on Railway — Holdroom UI uses Start call + `@elevenlabs/client`

Without an agent id, Holdroom uses **browser continuous conversation** (auto-listen after each reply).

In Vapi assistant → custom LLM base URL:

```text
https://<service>.up.railway.app/v1
```

Orchestrator remains the brain; Vapi is transport only.

---

## 5. Local parity (before / while deploying)

```bash
cd "/Users/apple/Desktop/Voice Agent"
# API + UI together (AAS_API_BASE empty)
PYTHONPATH=src python3 -m api.chat
# open http://127.0.0.1:8000/
```

Docker parity with Railway:

```bash
docker build -t advisor-aas .
docker run --rm -p 8000:8000 --env-file .env advisor-aas
```

CI (unchanged):

```bash
PYTHONPATH=src pytest -q -m "not live_mcp and not voice"
```

---

## 6. Environment reference

Mirror `.env.example`. Production differences:

| Concern | Local | Railway + Vercel |
|---------|-------|------------------|
| Google auth | OAuth files OK | **`GOOGLE_SERVICE_ACCOUNT_JSON` only** |
| UI origin | `http://127.0.0.1:8000` | Vercel HTTPS |
| API origin | same host | Railway HTTPS |
| CORS | `*` fine | Restrict to Vercel origin(s) |
| Sessions | In-memory | Reset on Railway restart / scale (expected for demo) |
| Disk | Writable | Ephemeral — do not rely on writing `token.json` |

---

## 7. Free / cost notes

| Host | Expectation |
|------|-------------|
| **Vercel** | Hobby free for this static UI |
| **Railway** | Trial/hobby credits; may require card for verification — not the same as a fixed $7 Render instance |
| Cold starts | First request after idle can be slow on hobby tiers |
| Gemini | Free-tier 429s → app already falls back to direct booking tools |

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| CORS blocks Vercel → Railway | Set `CORS_ORIGINS` to exact Vercel URL(s) |
| Wrong / empty `AAS_API_BASE` | Sessions hit Vercel (404); set Railway URL in `web/config.js` and redeploy Vercel |
| Gemini 429 | Direct Calendar → Docs → Gmail fallback already in code; switch model/quota |
| SA not shared on Calendar | Share calendar with SA email as Editor |
| Secrets in git | Keep `.env` gitignored; only set in Railway Variables |
| Mic / silent TTS | Chrome/Edge; tap to unlock speechSynthesis (existing UI) |
| In-memory session loss | Expected on Railway restart; user hits Restart |

---

## 9. Success criteria

- [ ] Railway `/health` returns `"status":"ok"`.
- [ ] Vercel serves the **latest** voice console (stage, chips, hold-to-talk, TTS).
- [ ] Browser on Vercel completes Acknowledge → Name → Book → Confirm against Railway.
- [ ] Topic labels show **KYC Onboarding** / **SIP Mandates** (product copy).
- [ ] Calendar (and Docs/Gmail as configured) reflect the booking with customer name.
- [ ] No secrets committed to GitHub.
- [ ] (Optional) Vapi custom-LLM reaches Railway `/v1`.

---

## 10. Decision summary

| Question | Decision |
|----------|----------|
| Where does the latest frontend run? | **Vercel** (`web/` root) |
| Where does the backend run? | **Railway** (Docker / Uvicorn) |
| How does the UI find the API? | Vercel env `AAS_API_BASE` → `inject-api-base.js` → `config.js` |
| Streamlit / Render as primary? | **No** — Railway + Vercel only for this plan |
| Single-host fallback? | Open Railway URL (serves API + same `web/` from image) |

---

## 11. Checklist (copy/paste)

1. [ ] Push latest `main` (frontend + Docker + `railway.toml` + `web/` Vercel files)
2. [ ] Deploy Railway from GitHub; set env vars; public domain
3. [ ] `curl …/health` OK
4. [ ] Vercel Root Directory `web`; env `AAS_API_BASE` → Railway URL; deploy
5. [ ] Set Railway `CORS_ORIGINS` → Vercel origin
6. [ ] E2E voice booking smoke on Vercel URL
7. [ ] (Optional) Point Vapi at Railway `/v1`
