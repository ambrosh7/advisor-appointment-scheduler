# Low-Level Architecture — Advisor Appointment Scheduler

This document turns the logical design into implementation-level modules, interfaces, data shapes, and a **phase-by-phase** build plan. Stack choices below are suggested defaults; keep the same seams if you swap libraries.

**Related docs:** [problemStatement.md](./problemStatement.md)

---

## Development rule: chat first, voice second

Ship a full chat experience before any audio. All flows (book, reschedule, cancel, prepare, availability, waitlist, Google MCP) are implemented and tested with **text in → text out** only.

| Rule | Detail |
|---|---|
| Single core API | `Orchestrator.handle(user_text, session) -> AgentTurn` — `AgentTurn` contains one or more assistant text messages (and internal side effects) |
| Chat | UI and HTTP APIs call `handle` directly |
| Voice | Adapter only: STT → `user_text`; each assistant string → TTS. Orchestrator, NLU, domain, and Google MCP stay unchanged |

**Phases 1–6** complete the chat agent. **Phase 7** adds STT/TTS and real-time audio. **Phase 8** hardens production for either channel.

---

## Cross-cutting conventions (all phases)

| Concern | Implementation detail |
|---|---|
| Time | Store `Instant` (UTC) + `ZoneId` (`Asia/Kolkata`) for display. Single injectable `Clock` for tests |
| IDs | `session_id` (UUID), `correlation_id` (propagate to MCP/logging) |
| Idempotency | Calendar create uses key `booking:{code}` (or hash of code + slot start) to avoid duplicate holds on retries |
| Config | Env-driven: Google OAuth/service-account credentials, Gemini API key, secure link base URL. Default mode text/chat. Secrets in `.env` (gitignored) |

### Suggested repo layout

```text
src/
  domain/           # pure: topics, codes, calendar rules, DTOs
  session/          # state machine, session store, Orchestrator (text in / text out)
  nlu/              # prompts, parsers, PII guard
  integrations/
    google_mcp/     # FastMCP server: real Google Calendar, Docs, Gmail tools
    voice/          # stt, tts only — thin wrappers; optional until Phase 7
  api/
    chat/           # REST or WebSocket messages: primary surface Phases 1–6
    voice/          # optional: audio session bridge (Phase 7)
tests/
  unit/
  integration/      # chat HTTP or in-process handle(); Google MCP integration against live APIs
```

---

## Phase 1 — Domain + mock calendar

**Goal:** Pure booking logic with zero I/O. Foundation for every later phase.

### Deliverables

#### 1.1 Enumerations and constants

| Type | Values |
|---|---|
| `Topic` | Closed enum matching problem statement (exact string keys for MCP titles): KYC/Onboarding, SIP/Mandates, Statements/Tax Docs, Withdrawals & Timelines, Account Changes/Nominee |
| `Intent` | `book_new` \| `reschedule` \| `cancel` \| `what_to_prepare` \| `check_availability` \| `unknown` |
| `AdvisorDisclaimerStatus` | `pending` \| `acknowledged` |

#### 1.2 DTOs (serializable, no PII)

```text
TimeSlot
  start_utc: ISO-8601 instant
  end_utc: ISO-8601 instant
  label_ist: string   # e.g. "Tuesday, 8 April 2026, 3:00 PM IST"

BookingPreference
  topic: Topic
  preferred_date_ist: LocalDate | null
  preferred_time_window: morning | afternoon | evening | exact | null
  raw_user_phrase: string | null

BookingRecord
  code: string                    # e.g. NL-A742
  topic: Topic
  slot: TimeSlot
  created_at_utc: instant
  status: tentative | waitlisted | cancelled
```

#### 1.3 `BookingCodeGenerator`

| Aspect | Detail |
|---|---|
| Input | None, or optional entropy seed for tests |
| Output | Pattern `[A-Z]{2}-[A-Z][0-9]{3}` (configurable) |
| Uniqueness | Check against `BookingStore`; collision retry with cap (e.g. 5) |
| Voice later | `to_spelling(code) -> string` for TTS (“N L dash A seven four two”); chat shows raw code |

#### 1.4 `MockCalendarService` (interface + impl)

```text
findTwoSlots(preference: BookingPreference, now: Clock): TimeSlot[]
  - Returns 0, 1, or 2 slots (pad/truncate to 2 per product rule)
  - Deterministic mode for tests: fixed seed or injected slot list
  - Empty => orchestrator triggers waitlist (not this class)

holdWaitlistSlot(preference, code): TimeSlot | null
  - Optional synthetic waitlist marker slot
```

**Implementation sketch:** Predefine advisor working hours in IST; filter by `preferred_date_ist` / window; return next two free slots from an in-memory “busy” set updated on each confirm in dev.

#### 1.5 `BookingStore` (interface)

- `save(record)`, `get_by_code(code)`, `update_status(code, status)`
- Phase 1–2: in-memory dict
- Later: optional Redis with TTL (e.g. 7 days) for multi-instance workers

#### 1.6 IST formatting

- `formatSlotForUser(slot) -> string` — used in chat and later read by TTS

### Exit criteria

- Unit tests green for: format, uniqueness, collision retry, boundary dates, empty calendar, two-slot truncation
- **No I/O**

---

## Phase 2 — State machine + chat entrypoint

**Goal:** Full happy path to “ready to confirm” via chat/CLI, without MCP or audio.

### Deliverables

#### 2.1 State enum

```text
GREET
DISCLAIMER_AWAIT_ACK
INTENT_ROUTING
BOOK_TOPIC
BOOK_TIME_PREFERENCE
BOOK_OFFER_SLOTS
BOOK_CONFIRM
BOOK_EXECUTE_MCP        # transient; on failure -> BOOK_OFFER_SLOTS or ERROR_RECOVER
CLOSE
# branches (wired in Phase 6)
RESCHEDULE_COLLECT_CODE
RESCHEDULE_OFFER_SLOTS
CANCEL_COLLECT_CODE
CANCEL_CONFIRM
PREPARE_TOPIC_OR_GENERIC
AVAILABILITY_QUERY
ERROR_RECOVER
```

#### 2.2 `SessionContext` (per `session_id`)

```text
state: State
disclaimer: AdvisorDisclaimerStatus
intent: Intent | null
preference: BookingPreference | partial
offered_slots: TimeSlot[]        # length 0–2
selected_slot: TimeSlot | null
pending_booking_code: string | null
last_mcp_error: string | null    # sanitized
turn_count: int
advice_redirect_count: int       # cap retries on advice loop
```

#### 2.3 Orchestrator transition pipeline

Implement as `Orchestrator.handle(user_text, session) -> AgentTurn`:

1. **PII gate** (regex + optional classifier): if match → fixed reply + secure URL; do not advance state (or → `CLOSE` if policy ends session)
2. **Advice gate**: if investment advice → static refusal + links; stay in current state or `INTENT_ROUTING`
3. **NLU step**: produce `NluResult { intent, entities, confidence }` (stub in this phase)
4. **State handler**: `(State, NluResult, SessionContext) -> (new State, side_effects[])`
5. **Side effects** (ordered queue per turn):
   - `emit_assistant_text(text)` — append to turn messages (chat renders; voice feeds TTS later)
   - Google MCP calls (Phase 4+)
   - `persist_session`
6. Execute side effects after state commit; on MCP failure → recovery state + apology/retry message

#### 2.4 `SessionStore`

- `get(session_id)`, `put(session)`, TTL (e.g. 30 min idle)
- Thread-safe if multiple workers

#### 2.5 Chat transport

| Endpoint / surface | Behavior |
|---|---|
| `POST /session` | Create session, return `session_id` |
| `POST /session/{id}/message` | Body `{ "text": "..." }` → `{ "messages": ["..."], "state": "..." }` |
| Optional `GET /session/{id}` | Debug state (disable in prod if needed) |
| CLI REPL | Forward text to `handle`, print returned messages |
| Web UI | Thin client over same endpoints; **no booking logic in browser** |

#### 2.6 Phase-2-scoped gates

- Disclaimer: cannot pass without ack phrase (“yes” / “I understand”)
- PII regex gate (phone/email patterns) → canned chat response
- Stub NLU: typed commands (`topic kyc`, `time monday afternoon`) or literal phrases
- States from greet through offer slots

### Exit criteria

From chat UI or CLI, tester completes happy path to **“ready to confirm”** without MCP and without any audio code.

---

## Phase 3 — NLU wiring

**Goal:** Replace stub inputs with real intent/entity extraction; still chat-only.

### Deliverables

#### 3.1 Structured output schema

Force JSON (or tool call):

```json
{
  "intent": "book_new | reschedule | cancel | what_to_prepare | check_availability | unknown",
  "topic": "kyc_onboarding | ... | null",
  "date_phrase": "string | null",
  "time_window": "morning | afternoon | evening | null",
  "booking_code_guess": "string | null",
  "wants_investment_advice": false,
  "confidence": 0.0
}
```

#### 3.2 Resolver pipeline

| Component | Behavior |
|---|---|
| `RelativeDateResolver` | `date_phrase` + `today_ist` from Clock → `LocalDate` or `needs_clarification` |
| `TopicMapper` | Fuzzy match to `Topic` enum; below threshold → ask “Which of these five…” |
| `IntentPolicy` | If confidence < τ → one targeted clarification; cap N times per state |

#### 3.3 Prompt packaging

- **System:** allowed topics, disclaimer already handled, no PII, JSON only
- **User:** transcript + current state name + last assistant question (coreference)

#### 3.4 Interface

```text
NluEngine.parse(transcript, state, context) -> NluResult
```

Transcript is the same string whether from keyboard or STT later.

#### 3.5 Optional LLM-free shortcut

Keyword + regex router for demos; keep same `NluResult` type so orchestrator stays unchanged.

### Exit criteria

- Golden text fixtures for each intent label
- Clarification on ambiguous topic
- All runnable without voice

---

## Phase 4 — Actual Google MCP + LLM agent booking execution

**Goal:** On confirm, the **LLM agent calls real Google MCP tools** (Calendar, Docs/Email) so side effects land on live Google Workspace — not stubs or FakeMCP. Chat messages include booking code + secure URL.

**Rule:** Phase 4 uses **actual MCP only**. No FakeCalendar / FakeNotes / FakeEmail stand-ins for booking execution. Credentials and target Google resources must be configured in `.env`.

### Deliverables

#### 4.1 LLM agent → actual MCP tools

In `BOOK_EXECUTE_MCP`, the LLM agent is given the three real MCP tools and must invoke them (tool calls), not invent side effects in prose:

| MCP tool | Google product | Agent responsibility |
|---|---|---|
| `calendar_create_hold` | Google Calendar | Create tentative hold titled `Advisor Q&A — {Topic} — {Code}` |
| `docs_append_prebooking` | Google Docs | Append `{date, topic, slot, code}` to **Advisor Pre-Bookings** |
| `gmail_create_draft` | Gmail | Create approval-gated advisor email draft (never auto-send) |

Orchestrator still owns policy (when to enter `BOOK_EXECUTE_MCP`, what payload to pass). The agent executes the MCP tool calls against the live FastMCP server backed by Google APIs.

```text
BOOK_CONFIRM
    → BOOK_EXECUTE_MCP
         → LLM agent tool-calls:
              1. calendar_create_hold(...)     # real Calendar API
              2. docs_append_prebooking(...)   # real Docs API
              3. gmail_create_draft(...)       # real Gmail API
    → CLOSE (booking code + secure URL in chat)
```

#### 4.2 FastMCP server (real Google tools)

Server: `src/integrations/google_mcp/server.py`

```python
from fastmcp import FastMCP

mcp = FastMCP("advisor-booking")

@mcp.tool()
def calendar_create_hold(title: str, start_utc: str, end_utc: str,
                         calendar_id: str, idempotency_key: str) -> str:
    """Create a tentative calendar hold via Google Calendar API. Returns external_event_id."""

@mcp.tool()
def calendar_delete_hold(event_id: str, calendar_id: str) -> None:
    """Delete an existing tentative hold via Google Calendar API."""

@mcp.tool()
def docs_append_prebooking(doc_id: str, line: str,
                           idempotency_key: str) -> None:
    """Append a pre-booking line to the Advisor Pre-Bookings Google Doc. No PII."""

@mcp.tool()
def gmail_create_draft(to: str, subject: str,
                       body_markdown: str) -> str:
    """Create a real Gmail draft. Never auto-sends; returns draft_id."""
```

Each tool **must** call the live Google API via `google-api-python-client`. Do not ship FakeMCP implementations for these tools in the Phase 4 agent path.

#### 4.3 Google API backing (live)

| MCP tool | Google API | Python service |
|---|---|---|
| `calendar_create_hold` / `calendar_delete_hold` | Calendar API v3 | `build("calendar", "v3")` |
| `docs_append_prebooking` | Docs API v1 | `build("docs", "v1")` |
| `gmail_create_draft` | Gmail API v1 | `build("gmail", "v1")` |

| Concern | Detail |
|---|---|
| Auth | OAuth 2.0 or service account from `.env`; shared `Credentials` at startup — **required** for Phase 4 |
| Timeouts | Calendar 5–10s; Docs/Gmail 5s; single retry on transient network |
| Logging | `correlation_id`, tool name, latency, success/failure — not full email body if sensitive |
| Verification | Confirm in Google Calendar UI, Docs doc, and Gmail Drafts after a successful chat booking |

#### 4.4 `ExecuteBookingSideEffects` (LLM agent use case)

Invoked from `BOOK_EXECUTE_MCP` — agent performs **actual** MCP tool calls in order:

1. Generate booking code if not set
2. Agent calls `calendar_create_hold(...)` → live Calendar event `Advisor Q&A — {Topic} — {code}`
3. Agent calls `docs_append_prebooking(formatted_line, idempotency_key=code)` → live Docs append
4. Agent calls `gmail_create_draft(subject, body_with_code_and_slot_ist, ...)` → live Gmail draft
5. On partial failure: compensating actions (e.g. `calendar_delete_hold` if Docs append failed); surface user-friendly error

#### 4.5 Wire confirm → close

- `BOOK_CONFIRM` → `BOOK_EXECUTE_MCP` → `CLOSE`
- Chat messages include booking code + secure URL template: `https://example.com/complete?ref={code}`
- Dependencies: `fastmcp`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`

### Exit criteria

- Integration via chat API: full `book_new` with two slots → **real** Google Calendar event, **real** Docs entry, **real** Gmail draft
- LLM agent tool-call trace shows the three MCP tools invoked (not simulated)
- Manual check in Google Workspace UIs confirms the three artifacts

---

## Phase 5 — Waitlist + advice refusal

**Goal:** Empty-calendar and investment-advice paths; IST repeated on confirm.

### Deliverables

| Path | Implementation |
|---|---|
| Waitlist | `findTwoSlots` empty → waitlist transition; optional `holdWaitlistSlot` or notes-only per PM; always `email.createAdvisorDraft` via MCP |
| Advice refusal | Classifier or keyword path + educational link constants in config |
| IST confirm | Repeat full date/time IST on final confirm (assert in test output) |

### Exit criteria

Separate integration tests for:

1. Empty calendar → waitlist
2. Advice interruption mid-flow

---

## Phase 6 — Secondary intents (subgraphs)

**Goal:** Complete all five intents through chat; no PII prompts.

### Deliverables

| Intent | Flow |
|---|---|
| **Reschedule** | `RESCHEDULE_COLLECT_CODE` → validate code in `BookingStore` → offer two new slots → Calendar MCP update (delete old hold + create new) |
| **Cancel** | Collect code → confirm → `calendar_delete_hold` + Docs append “cancelled” + optional Gmail draft |
| **what_to_prepare** | Map `Topic` to static markdown snippets; no LLM invention |
| **check_availability** | `MockCalendarService` in “peek” mode (no booking); then suggest `book_new` |

### Exit criteria

Each subgraph has an integration test through chat; no PII prompts.

---

## Phase 7 — Voice adapters (I/O swap only)

**Prerequisites:** Phases 1–6 green; chat is the regression baseline.

**Goal:** STT/TTS around the same `handle` pipeline — no reimplementation of booking logic.

### Pipeline

```text
[Mic] → SpeechToText → user_text → Orchestrator.handle(...) → assistant_messages[]
                                                             → TextToSpeech → [Speaker]
```

### Deliverables

#### 7.1 Abstractions

| Interface | Role |
|---|---|
| `SpeechToText` | Stream or batch; partial + final transcripts → string |
| `TextToSpeech` | `synthesize(assistant_message)`; optional spell-out for booking codes |
| `AudioIO` | Chunk frames in/out (platform-specific) |

#### 7.2 Integration pattern

- VAD + end-of-utterance → final string → same contract as chat (one user message per completed utterance)
- Barge-in: cancel current TTS on speech start; session state matches chat history semantics
- Confirm step: TTS reads orchestrator IST strings verbatim; optional `to_spelling(code)` for booking code line only
- Slot choice (“first” / “second”) uses same NLU as typing “first slot”
- Parallel surface: WebSocket audio or telephony webhook → decode → same `handle` / message handler
- Stream partial transcripts for UX only; commit turn when utterance is final

### Exit criteria

- One E2E voice test (manual checklist acceptable)
- Chat suite still passes unchanged (or expanded only for shared copy tweaks)
- End-to-end latency budget documented (STT + orchestrator + TTS)

---

## Phase 8 — Hardening and ops

**Goal:** Production readiness for chat and/or voice.

### Deliverables

| Area | Detail |
|---|---|
| Logging | Structured logs + `correlation_id`; redact stored/logged user text (chat and STT) in prod |
| Session ops | Rate limits on session create; session TTL job (shared by chat and voice) |
| Runbook | Google MCP outage: queue Gmail draft only, tell user to retry — same strings in chat or voice |
| Failure injection | Tests against real MCP timeouts/errors via chat API; documented degraded mode |

### Exit criteria

- Failure-injection / degraded-mode behavior verified against actual Google MCP
- Degraded mode documented
- Voice optional in CI; **chat + live Google MCP integration remain the default gate**

---

## Logical architecture (reference)

Build order: everything below the dashed line via chat first; voice adapters only after chat is complete.

```text
┌─────────────────────────────────────────────────────────────────┐
│  Voice adapters (Phase 7): telephony / WebRTC + STT → text,     │
│                            TTS ← text                           │
└─────────────────────────────┬───────────────────────────────────┘
                              │ text only
┌─────────────────────────────▼───────────────────────────────────┐
│  Chat channel (Phases 1–6): web UI, CLI, or HTTP message API    │
└─────────────────────────────┬───────────────────────────────────┘
                              │ user_text / assistant_messages
- - - - - - - - - - - - - - - ┼ - - - - - - - - - - - - - - - - -
┌─────────────────────────────▼───────────────────────────────────┐
│  Conversation orchestrator (state machine + policy)             │
│  • Intent routing (5 intents)                                   │
│  • Slot collection & validation                                 │
│  • Compliance gates (disclaimer, advice refusal)                │
└─────┬───────────────────┬───────────────────┬───────────────────┘
      ▼                   ▼                   ▼
┌───────────┐   ┌───────────────┐   ┌────────────────────────────────────┐
│ NLU / LLM │   │ Booking       │   │ Actual Google MCP (live APIs)      │
│ classify, │   │ domain logic  │   │ Calendar / Docs / Gmail tools      │
│ generate, │   │ topics, slots │   │ LLM agent tool-calls in Phase 4    │
│ tool-call │   │ codes, IST    │   └────────────────────────────────────┘
└───────────┘   └───────────────┘
```

**Principle:** Orchestrator owns turn-taking and compliance; LLM assists understanding/phrasing and, in Phase 4, **calls actual Google MCP tools** for Calendar, Docs, and Gmail. It cannot skip disclaimer or accept PII.

---

## Traceability to requirements

| Requirement | Where implemented |
|---|---|
| Five intents | Intent + NLU + state branches (Phases 2–6), verified in chat |
| Disclaimer + topic list + IST | States `DISCLAIMER_*`, `BOOK_TOPIC`, formatters (Phases 1–2) |
| Two slots | `MockCalendarService`, `BOOK_OFFER_SLOTS` (Phases 1–2) |
| Booking code + actual Google MCP (Calendar, Docs, Gmail) | LLM agent tool-calls via `ExecuteBookingSideEffects` (Phase 4) |
| No PII | PII gate + NLU system prompt (Phases 2–3) |
| No investment advice | Advice gate + static links (Phase 5) |
| Waitlist + email | Phase 5 |
| Secure URL | Config template in `CLOSE` (Phase 4) |
| Voice UX | Phase 7: STT/TTS only; core unchanged |

---

## Open decisions (lock with PM)

1. Whether waitlist uses the same booking code format as confirmed slots
2. Whether reschedule/cancel require code only (no phone lookup — aligned with no PII); chat validates the same flow before voice
3. Exact secure URL issuer and token model (out of band to this stack)
