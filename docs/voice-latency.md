# Voice end-to-end latency budget (Phase 7)

Measured per completed utterance after VAD / end-of-utterance. Values are engineering targets for local or near-region STT/TTS; MCP booking turns are excluded from the “no side effects” row.

| Stage | p50 target | p95 target | Notes |
|---|---|---|---|
| **STT finalize** | ≤ 500 ms | ≤ 1 500 ms | After end-of-utterance; streaming partials do not count |
| **Orchestrator.handle** | ≤ 200 ms | ≤ 800 ms | NLU + state machine only (no Google MCP) |
| **Orchestrator + MCP** | ≤ 2 500 ms | ≤ 8 000 ms | Confirm / cancel / reschedule tool calls |
| **TTS time-to-first-audio** | ≤ 400 ms | ≤ 1 200 ms | Prefer streaming synthesis |
| **E2E turn (no MCP)** | ≤ 1.5 s | ≤ 4 s | STT + orch + TTS first playable audio |

## How we measure

The `VoicePipeline` records `LatencyBreakdown` on each `VoiceTurnResult`:

- `stt_ms` — finalize / inject transcript
- `orchestrator_ms` — `Orchestrator.handle`
- `tts_ms` — synthesize + write all assistant messages for the turn

WebSocket `assistant_turn` / `session_started` payloads include `latency_ms` for live checks. The simulated CLI prints the same breakdown each turn.

## Barge-in

On `speech_start` (or first mic chunk while TTS is active), TTS is cancelled and speaker playback stops. Session state is **not** rolled back — it already matches chat history semantics.
