# Phase 7 — manual voice E2E checklist

Automated coverage uses passthrough STT + recording TTS (`tests/integration/test_phase7_voice.py`). Use this list when a real mic/speaker (or telephony) is wired to the same adapters.

**Browser + Vapi:** see [vapi-setup.md](./vapi-setup.md).

## Setup

1. Chat suite green: `PYTHONPATH=src pytest -q`
2. **Browser voice UI:** `PYTHONPATH=src uvicorn api.chat.app:app --port 8000` → open `/`, hold mic
3. Or voice WS: `PYTHONPATH=src uvicorn api.voice.app:app --port 8001`
4. Or simulated REPL: `PYTHONPATH=src python -m api.voice`

## Checklist

- [ ] Connect WebSocket `ws://localhost:8001/ws/voice`, send `{"type":"start"}` — hear/see greet + disclaimer
- [ ] Speak or send `{"type":"text_utterance","text":"I understand"}` — state `INTENT_ROUTING`
- [ ] Book path: `book new` → topic → time → `first` → confirm prompt repeats **IST** date/time verbatim in TTS
- [ ] On confirm success, TTS spells booking code only (`N L dash …`); secure URL left as text
- [ ] Slot choice “first” / “second” behaves like typed chat
- [ ] Mid-TTS: send `{"type":"speech_start"}` — receive `tts_cancelled`; session state unchanged
- [ ] Partial transcripts appear on `audio_chunk` / feed; turn commits only on `utterance_end` or `text_utterance`
- [ ] No PII prompts; phone/email still redirected
- [ ] Chat HTTP suite still passes unchanged after voice changes

## Notes

- Real STT/TTS providers should implement `SpeechToText` / `TextToSpeech` / `AudioIO` without changing `Orchestrator`
- Latency targets: see [voice-latency.md](./voice-latency.md)
