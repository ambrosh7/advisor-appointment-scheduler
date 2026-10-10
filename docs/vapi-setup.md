# Voice transport: browser vs Vapi

The **Orchestrator** stays the booking brain. Speech I/O is pluggable.

| Surface | STT / TTS / mic | Brain |
|---------|-----------------|--------|
| Browser demo (`/` on :8000) | Web Speech API + `speechSynthesis` | `POST /session/.../message` |
| Phone / WebRTC | **Vapi** | Custom LLM → `POST /v1/chat/completions` |

**Yes, connect Vapi** when you need phone numbers, production WebRTC, or reliable STT/TTS. Skip it for a local Chrome demo — the mic button already works.

## Browser (no Vapi)

1. `PYTHONPATH=src uvicorn api.chat.app:app --host 127.0.0.1 --port 8000`
2. Open `http://127.0.0.1:8000`
3. Allow microphone · hold mic · release to send · TTS speaks replies

## Vapi custom-LLM

1. Expose this API publicly (ngrok / Cloudflare Tunnel / deploy).
2. In Vapi → Assistant → Model:
   - Provider: **Custom LLM**
   - URL: `https://<your-host>/v1` (Vapi appends `/chat/completions`)
3. Set a short `firstMessage` (disclaimer ack prompt); booking turns come from our Orchestrator.
4. Optional client keys in `.env` (surfaced at `GET /voice/config`, no secrets):

```bash
VAPI_PUBLIC_KEY=
VAPI_ASSISTANT_ID=
```

5. Smoke-test the webhook locally:

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"I understand"}],"call":{"id":"demo-1"}}'
```

Streaming (`"stream": true`) returns OpenAI-style SSE for Vapi TTS pacing.

## What not to do

- Do not put booking / slot / cancel logic inside a Vapi prompt-only assistant.
- Do not send PII prompts through either surface — same Orchestrator guards apply.
