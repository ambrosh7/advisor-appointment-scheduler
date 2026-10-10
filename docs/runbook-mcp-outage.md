# Runbook — Google MCP outage

Same user-facing strings apply on **chat** and **voice**.

## Symptoms

- Confirm / cancel / reschedule returns retry messaging
- Health still `ok` but `phase4_side_effects` may be false if credentials failed at boot
- Logs: `mcp_booking_failed`, `mcp_degraded_gmail_queued`, or `google_api fail`

## Immediate actions

1. **Do not** invent calendar holds in the assistant.
2. Confirm degraded path queued an advisor draft (`[DEGRADED]` subject) when Gmail still works.
3. Tell the user (automated copy already does this) to **retry confirm** shortly.
4. Check Railway MCP / Google Calendar / Docs quotas and OAuth tokens.
5. After recovery, ask the user to confirm again — idempotency keys use `booking:{code}` / `degraded:{code}`.

## Operator checklist

| Check | Command / place |
|---|---|
| App health | `GET /health` — `phase4_side_effects`, `phase8_ttl_job` |
| Correlation | Logs include `correlation_id` (JSON when `LOG_JSON=1` / prod) |
| Gmail drafts | Look for `[DEGRADED] Advisor booking retry needed …` |
| Calendar | Google Calendar UI for `Advisor Q&A — {Topic} — {Code}` |
| Docs | Advisor Pre-Bookings doc append |

## Env knobs

| Variable | Purpose |
|---|---|
| `APP_ENV` | `production` enables JSON logs + user-text redaction by default |
| `REDACT_USER_TEXT` | Force on/off redaction of chat/STT text in logs |
| `SESSION_CREATE_RATE_LIMIT` | Max new sessions per window (default 30) |
| `SESSION_CREATE_RATE_WINDOW_S` | Window seconds (default 60) |
| `SESSION_TTL_MINUTES` | Idle session TTL (default 30) |
| `ENABLE_TTL_JOB` | Background purge (default on) |

## Escalation

If Gmail also fails, users see the no-email degraded string. Escalate to Google Workspace / MCP owners; bookings remain unconfirmed until a successful confirm.
