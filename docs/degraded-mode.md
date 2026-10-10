# Degraded mode (Phase 8)

When Google MCP Calendar/Docs (or the Gemini tool-calling agent) cannot complete a full booking, the stack enters **degraded mode**.

## Behavior

1. Primary path (`calendar_create_hold` → `docs_append_prebooking` → `gmail_create_draft`) fails.
2. **ResilientBookingSideEffects** queues an advisor **Gmail draft only** (`[DEGRADED]` subject) with topic, IST slot, booking code, and secure link.
3. The user is **not** marked booked. Session stays on `BOOK_CONFIRM`.
4. Assistant copy (identical for chat and voice):

   > I couldn’t complete the calendar hold just now. I’ve queued an advisor email draft with your booking details — please try confirming again in a moment.

5. User may confirm again when MCP recovers.

If Gmail queue also fails, copy falls back to `MCP_DEGRADED_RETRY_NO_EMAIL`.

## How to verify

- Automated: `tests/integration/test_phase8_hardening.py` injects Calendar/Docs timeouts and asserts degraded copy + `gmail_create_draft` in the tool trace.
- Live: temporarily break Calendar credentials or block the MCP URL, confirm via chat, check Gmail Drafts for `[DEGRADED]`.

See also [runbook-mcp-outage.md](./runbook-mcp-outage.md).
