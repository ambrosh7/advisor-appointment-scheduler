# ElevenLabs Conversational AI + Lockline

[ElevenLabs Conversational AI](https://join.elevenlabs.io/api/conversational-ai) runs the **voice loop** (mic streaming, turn-taking, interruption, natural TTS).  
**Lockline / Orchestrator** stays the **booking brain** via the same OpenAI-compatible custom LLM endpoint used for Vapi.

```text
User mic ──► ElevenLabs Agent (STT + TTS + turns)
                    │
                    │  Custom LLM (SSE)
                    ▼
         Railway POST /v1/chat/completions
                    │
                    ▼
              Orchestrator (booking states)
```

## 1. Create an ElevenLabs agent

1. Sign up / get an API key: [ElevenLabs API keys](https://elevenlabs.io/app/developers/api-keys)
2. Create a **Conversational AI** agent in the dashboard
3. Choose a natural voice (Flash / multilingual as you prefer)
4. System prompt (keep short — booking logic is server-side):

```text
You are Lockline, a voice booking assistant for tentative advisor appointments.
Follow the tool/LLM replies exactly. Do not invent booking codes or slots.
Never ask for phone, email, PAN, or bank details — those come later via a secure link.
Speak briefly. India time (IST) only.
```

5. First message: something like  
   `Hi — I’m Lockline. I can lock a tentative advisor slot. Reply yes if you understand this is not investment advice.`

## 2. Point the agent at our Orchestrator (custom LLM)

In the agent → **LLM / Custom LLM**:

| Setting | Value |
|---------|--------|
| Server URL | `https://advisor-appointment-scheduler-production.up.railway.app/v1` |
| Path | ElevenLabs appends `/chat/completions` (OpenAI-compatible) |
| Format | Chat Completions + SSE streaming |

Our Railway app already exposes `POST /v1/chat/completions` (same as Vapi).

Confirm CORS / public HTTPS on Railway. If ElevenLabs cannot reach localhost, use the Railway URL only.

## 3. Embed in Lockline (Vercel)

Set on Railway (surfaced to the UI via `GET /voice/config`):

```bash
ELEVENLABS_AGENT_ID=your_agent_id_here
```

Optional (widget auth / signed URLs later):

```bash
ELEVENLABS_API_KEY=  # server-only — never put in Vercel frontend
```

Redeploy Railway, hard-refresh Vercel. Lockline’s **Start call** control loads `@elevenlabs/client` (`Conversation.startSession`) when `agent_id` is present — natural turn-taking and TTS from ElevenLabs, booking brain still on Railway `/v1`.

Without an agent id, Lockline falls back to **browser continuous conversation** (Web Speech STT + TTS with auto-listen after each reply) — closer to an agent loop than push-to-talk.

## 4. Product positioning

| Layer | Owner |
|-------|--------|
| Natural voice, barge-in, latency | ElevenLabs |
| Disclaimer, name, slots, confirm, calendar | Lockline Orchestrator |
| UI brand | Lockline (`web/`) |

Do **not** put booking rules only inside the ElevenLabs prompt — keep them in the Orchestrator.

## 5. Free tier note

ElevenLabs offers free monthly credits for prototyping ([their Conversational AI product page](https://join.elevenlabs.io/api/conversational-ai)). Production volume needs a paid plan.
