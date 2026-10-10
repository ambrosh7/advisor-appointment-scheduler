# Deployment plan — Advisor Appointment Scheduler on Streamlit

> **Preferred production host for the current stack:** **[Render](./docs/deploy-render.md)** (Docker + FastAPI + `web/`).  
> Use this Streamlit plan only if you explicitly need a Streamlit Cloud surface.

This plan covers deploying the **full product** (booking Orchestrator / “backend” logic **and** the latest voice-console UX) with **Streamlit** as the public hosting surface.

---

## 1. Reality check (important)

| What we have today | What Streamlit Community Cloud runs |
|--------------------|-------------------------------------|
| FastAPI (`api.chat.app`) + static `web/` (HTML/CSS/JS) | A single `streamlit run <entry>.py` process |
| `uvicorn` on port 8000 | Streamlit on port 8501 (managed) |
| Browser mic → `POST /session/...` → Orchestrator | No long-lived custom FastAPI process on Streamlit Cloud |
| Vapi webhook `POST /v1/chat/completions` | Needs a public HTTP API host (not Streamlit Cloud alone) |

**Streamlit Community Cloud cannot run Uvicorn + FastAPI + static `web/` as a second server.**  
To put the *entire* product on Streamlit, we **in-process** the Orchestrator and present the voice UX through Streamlit (and/or embedded HTML). Keep FastAPI only if we also deploy an API host (hybrid).

---

## 2. Recommended architecture (all-on-Streamlit)

```text
┌─────────────────────────────────────────────────────────┐
│  Streamlit Community Cloud  (.streamlit.app)            │
│                                                         │
│  streamlit_app.py                                       │
│    ├─ UI: voice console (Streamlit + components.html)   │
│    ├─ st.session_state → Orchestrator session           │
│    ├─ Browser STT / TTS (same Web Speech as today)      │
│    └─ Google / Gemini / MCP via existing Python modules │
│                                                         │
│  PYTHONPATH=src  ·  secrets from Streamlit Secrets      │
└─────────────────────────────────────────────────────────┘
```

**Brain stays the same:** `session.orchestrator.Orchestrator` + Phase 4/8 side effects.  
**Transport changes:** Streamlit callbacks replace FastAPI `/session` routes for the interactive demo.

### Optional hybrid (only if you still need public HTTP APIs)

Use when you need **Vapi custom-LLM**, external webhooks, or the exact FastAPI OpenAPI surface:

| Piece | Host |
|-------|------|
| Voice / ops UI | Streamlit Cloud |
| FastAPI (`/session`, `/v1/chat/completions`, `/static`) | Render / Railway / Cloud Run |
| Streamlit calls | `BACKEND_URL` secret → `httpx` |

For “deploy everything on Streamlit” as the goal, **do not block on hybrid** — ship the in-process plan first.

---

## 3. Target repo layout (additions)

```text
Voice Agent/
├── streamlit_app.py              # Streamlit entry (Cloud “Main file path”)
├── streamlit_pages/              # optional multipage
│   ├── 1_Voice_Console.py
│   └── 2_Ops_Debug.py
├── streamlit_components/
│   └── voice_console.html        # trimmed export of web/ (or iframe bundle)
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example      # never commit real secrets
├── src/                          # existing backend (unchanged core)
├── web/                          # source of truth for console design
├── requirements.txt              # add streamlit, httpx if hybrid
├── packages.txt                  # only if system libs needed (usually empty)
└── deployment-plan.md            # this file
```

Keep `web/` as the design source; Streamlit either:

1. **Embeds** it via `st.components.v1.html` + `window.parent` / custom component messaging, or  
2. **Reimplements** the console with Streamlit widgets + a small JS mic component that posts transcripts into `st.session_state`.

**Preference for fidelity:** embed a packaged `voice_console.html` that calls a tiny JS bridge (`Streamlit.setComponentValue`) instead of FastAPI fetch — so look/feel matches the latest frontend without a separate web server.

---

## 4. Streamlit app contract (backend in-process)

### 4.1 Session lifecycle

| Action | Implementation |
|--------|----------------|
| Start / Restart | `orch.create_session()` → store `session_id`, `AgentTurn` in `st.session_state` |
| User text / STT final | `orch.handle(text, session)` |
| State / stepper | Map `session.state` → same stage labels as `web/app.js` |
| Name / topic / slots | Existing Orchestrator states (`COLLECT_NAME`, `BOOK_*`, …) |
| Debug | Expandable “Turn history” from messages list (same as compact log) |

### 4.2 Singleton Orchestrator

```python
# Pseudocode — one Orchestrator per Streamlit server process
@st.cache_resource
def get_orchestrator() -> Orchestrator:
    load_dotenv_or_secrets()
    return build_orchestrator_from_env()  # same wiring as api.chat.app.create_app
```

Per-browser session: only `session_id` + UI flags in `st.session_state`.

### 4.3 Voice (STT / TTS)

| Capability | On Streamlit |
|------------|--------------|
| Hold-to-talk STT | Keep Web Speech API inside embedded HTML / custom component (Chrome/Edge) |
| TTS en-US + KYC/SIP expansion | Same `speechSynthesis` logic as `web/app.js` (`forSpeech`) |
| Barge-in | Cancel TTS on mic `pointerdown` (already in frontend) |
| Server-side STT/TTS | Out of scope for Cloud free tier; optional later via Vapi hybrid |

### 4.4 What does **not** move onto Streamlit Cloud alone

- **Vapi** `POST /v1/chat/completions` — needs FastAPI (or equivalent) on a public URL  
- Long-running WebSocket voice app (`api.voice`) — keep optional / hybrid  
- Local Google OAuth browser redirect — prefer **service account** JSON in secrets for Cloud

---

## 5. Secrets & configuration

### 5.1 Streamlit Secrets (Community Cloud → App settings → Secrets)

Mirror `.env` / `.env.example` as TOML:

```toml
GEMINI_API_KEY = "..."
GEMINI_MODEL = "gemini-2.5-flash"          # prefer a model with headroom vs free-tier 429s
GOOGLE_CALENDAR_ID = "primary"
GOOGLE_DOCS_PREBOOKING_ID = "..."
GOOGLE_GMAIL_ADVISOR_TO = "advisor@example.com"
SECURE_LINK_TEMPLATE = "https://example.com/complete?ref={code}"
ADVICE_EDUCATIONAL_URL = "https://example.com/learn/basics"
MCP_SERVER_URL = "https://.../mcp"
MCP_HTTP_BEARER_TOKEN = "..."

# Preferred on Streamlit Cloud (no interactive OAuth)
GOOGLE_SERVICE_ACCOUNT_JSON = """{ ... raw json ... }"""

# Hybrid only
# BACKEND_URL = "https://your-api.onrender.com"
```

At startup, map secrets → `os.environ` before `GoogleMcpConfig.from_env()` / Phase 4 factory.

### 5.2 Google credentials strategy

| Auth mode | Streamlit Cloud |
|-----------|-----------------|
| OAuth `credentials.json` + local `token.json` | Fragile (no durable local disk, no easy consent UX) |
| **Service account** + shared calendar/docs | **Recommended** |
| MCP Railway bearer for Docs/Gmail | Keep as today |

Document calendar/docs sharing with the service-account email.

### 5.3 Rate limits / Gemini 429

Booking already has **direct Calendar → Docs → Gmail fallback** when Gemini is exhausted. On Streamlit:

- Prefer a paid Gemini tier or a less-constrained model ID in secrets  
- Keep NLU rule fallback (already used when Gemini NLU fails)  
- Surface a friendly “Working offline from AI quota — booking tools still running” banner if direct fallback is used (optional UX)

---

## 6. Dependencies

Update `requirements.txt` (Streamlit Cloud installs this from repo root):

```text
streamlit>=1.32
fastapi>=0.110          # keep if hybrid or shared models; optional for pure in-process
uvicorn[standard]>=0.27 # hybrid / local only
httpx>=0.27             # hybrid Streamlit → API
pydantic>=2.0
python-dotenv>=1.0
google-api-python-client>=2.100
google-auth>=2.28
google-auth-oauthlib>=1.2
google-generativeai>=0.8
google-genai>=1.0
```

Pin Python **3.11+** in Cloud (Google libs warn on 3.9).

`.streamlit/config.toml` (example):

```toml
[server]
headless = true
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#C8F06C"
backgroundColor = "#E8EEF2"
secondaryBackgroundColor = "#F3F7F5"
textColor = "#0B1F2A"
font = "sans serif"
```

---

## 7. Implementation phases

### Phase A — Streamlit skeleton (1–2 days)

1. Add `streamlit_app.py` with brand header + stepper placeholders.  
2. `@st.cache_resource` Orchestrator (mock calendar first).  
3. Text input path: disclaimer → name → intent → book (parity with chat API).  
4. Show assistant messages in a “Live response” panel.  
5. Local: `PYTHONPATH=src streamlit run streamlit_app.py`.

**Exit criteria:** Full book/confirm path works without FastAPI.

### Phase B — Latest frontend parity (2–3 days)

1. Package `web/index.html` + CSS/JS into `streamlit_components/voice_console.html`.  
2. Replace `fetch("/session...")` with Streamlit component bridge:
   - JS → `Streamlit.setComponentValue({ type, text })`
   - Python → `orch.handle` → `st.components` re-render / `postMessage` reply  
3. Preserve: hold-to-talk, TTS unlock, en-US voice, KYC/SIP speech expansion, stage fill, chips.  
4. Wire Restart / TTS / theme to Streamlit or keep inside the component.

**Exit criteria:** Visual/interaction match of current console on `localhost:8501`.

### Phase C — Production secrets & Google (1–2 days)

1. Service account + MCP secrets in Streamlit Cloud.  
2. Smoke: calendar hold title includes **customer name**; docs line + Gmail draft OK.  
3. Confirm degraded copy still correct if Docs/Gmail remote fails.  
4. Hide raw state machine strings (already productized in UI).

**Exit criteria:** Real booking from Cloud URL.

### Phase D — Hardening (1 day)

1. Session TTL / restart hygiene under Streamlit reruns.  
2. Redact phone/email in any logged Streamlit exceptions (reuse `ops.logging`).  
3. Basic AppTest or scripted smoke for disclaimer → name → book new.  
4. README “Deploy” section linking this plan.

### Phase E — Optional hybrid API (only if needed)

1. Deploy FastAPI to Render/Railway (`uvicorn api.chat.app:app --host 0.0.0.0 --port $PORT`).  
2. Point Vapi custom-LLM at `https://<api>/v1`.  
3. Streamlit either stays in-process **or** switches to `BACKEND_URL` for demos that must share sessions with phone.

---

## 8. Streamlit Community Cloud checklist

1. Push repo to GitHub (public or private with Cloud access).  
2. [share.streamlit.io](https://share.streamlit.io) → **New app**.  
3. **Main file path:** `streamlit_app.py`.  
4. **Python version:** 3.11+.  
5. Paste Secrets (section 5).  
6. Deploy → open `https://<app>.streamlit.app`.  
7. Hard-refresh; allow microphone; click **TTS on** once (browser gesture).  
8. Flow: Acknowledge → **Full name** → Book new → KYC Onboarding → time → slot → confirm.  
9. Verify Calendar event summary contains name + code; Gmail draft queued/created.

---

## 9. Local verification (before Cloud)

```bash
cd "/Users/apple/Desktop/Voice Agent"
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
# load .env or .streamlit/secrets.toml for local
streamlit run streamlit_app.py
```

Parallel (optional, hybrid):

```bash
PYTHONPATH=src uvicorn api.chat.app:app --host 127.0.0.1 --port 8000
```

CI gate (unchanged):

```bash
PYTHONPATH=src pytest -q -m "not live_mcp and not voice"
```

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Streamlit rerun clears widget state | Persist `session_id` in `st.session_state`; Orchestrator in `cache_resource` |
| Mic / TTS blocked | Same unlock pattern as `web/app.js`; show “Tap to enable voice” |
| Gemini free-tier 429 | Direct booking fallback (already in code); upgrade model/quota |
| OAuth token path on Cloud | Service account JSON in secrets |
| Custom component bridge lag | Keep turns small; disable unnecessary Streamlit reruns with `on_change` patterns |
| Vapi phone not on Streamlit | Phase E hybrid API |
| Secrets in git | `.streamlit/secrets.toml` gitignored; only `secrets.toml.example` committed |

---

## 11. Success criteria

- [ ] Public Streamlit URL runs the **latest** voice-console experience (or faithful embed).  
- [ ] Full booking path works end-to-end with **customer name** on calendar/docs/email.  
- [ ] Topics display **KYC Onboarding** / **SIP Mandates** (no slash).  
- [ ] No dependency on local `uvicorn` for the primary demo.  
- [ ] Secrets only via Streamlit Secrets / env — not in the repo.  
- [ ] (Optional) Vapi reachable via separately deployed FastAPI.

---

## 12. Decision summary

| Question | Decision |
|----------|----------|
| Can we deploy “as-is” FastAPI + `web/` only on Streamlit Cloud? | **No** |
| How do we put backend + latest frontend on Streamlit? | **In-process Orchestrator + Streamlit UI / embedded console** |
| Keep FastAPI? | **Yes locally & for Vapi**; optional Cloud sibling host |
| First Cloud milestone | Phases **A → C** above |

---

## 13. Next engineering tasks (after plan approval)

1. Implement `streamlit_app.py` + `get_orchestrator()`.  
2. Add component bridge from `web/app.js` (replace `fetch` with Streamlit messaging).  
3. Add `.streamlit/secrets.toml.example` and gitignore rules.  
4. Extend `requirements.txt` with `streamlit`.  
5. Deploy to Streamlit Cloud and run the checklist in §8.
