"""
Simulated voice REPL — typed lines are treated as final STT transcripts.

Speaks assistant turns through RecordingTextToSpeech (prints spoken form).

Usage:
  PYTHONPATH=src python -m api.voice
"""

from __future__ import annotations

import logging

from domain.calendar import MockCalendarService
from domain.clock import SystemClock
from integrations.booking_agent.factory import build_phase4_side_effects
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.voice.audio_io import MemoryAudioIO
from integrations.voice.pipeline import VoicePipeline
from integrations.voice.stt import PassthroughSpeechToText
from integrations.voice.tts import RecordingTextToSpeech
from nlu.engine import build_default_nlu_engine
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore

logger = logging.getLogger(__name__)


def _print_voice_turn(result) -> None:
    print(f"\n—— state={result.state.value}  "
          f"latency(ms) stt={result.latency.stt_ms:.1f} "
          f"orch={result.latency.orchestrator_ms:.1f} "
          f"tts={result.latency.tts_ms:.1f} "
          f"total={result.latency.total_ms:.1f} ——")
    if result.final_transcript:
        print(f"STT final: {result.final_transcript!r}")
    for i, (chat, spoken) in enumerate(
        zip(result.messages, result.spoken_messages), start=1
    ):
        print(f"\nAssistant[{i}] (chat):\n{chat}")
        if spoken != chat:
            print(f"\nAssistant[{i}] (TTS spoken):\n{spoken}")
    if result.barge_in:
        print("\n(TTS cancelled — barge-in)")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    clock = SystemClock()
    config = GoogleMcpConfig.from_env()
    booking_fx = waitlist_fx = cancel_fx = reschedule_fx = None
    errors = config.validate_for_live()
    if not errors:
        try:
            phase4 = build_phase4_side_effects(config)
            booking_fx = phase4.booking
            waitlist_fx = phase4.waitlist
            cancel_fx = phase4.cancel
            reschedule_fx = phase4.reschedule
            print("Google MCP side effects enabled for voice demo.")
        except Exception as exc:  # noqa: BLE001
            print(f"MCP side effects disabled ({exc}).")
    else:
        print("MCP side effects disabled: " + "; ".join(errors))

    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=build_default_nlu_engine(clock=clock, use_llm=False),
        clock=clock,
        booking_side_effects=booking_fx,
        waitlist_side_effects=waitlist_fx,
        cancel_side_effects=cancel_fx,
        reschedule_side_effects=reschedule_fx,
        google_config=config,
    )
    pipeline = VoicePipeline(
        orch,
        stt=PassthroughSpeechToText(),
        tts=RecordingTextToSpeech(),
        audio_io=MemoryAudioIO(),
        spell_booking_codes=True,
    )

    print("Voice simulation (typed text = final STT). Commands: /quit, /barge")
    result = pipeline.start_session()
    print(f"Session {result.session_id}")
    _print_voice_turn(result)

    while True:
        try:
            text = input("\nYou (spoken)> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not text:
            continue
        if text in {"/quit", "/exit", "quit", "exit"}:
            print("Bye.")
            break
        if text == "/barge":
            pipeline.on_speech_start()
            print("TTS cancelled (barge-in). Session state unchanged.")
            continue
        result = pipeline.commit_utterance(text)
        _print_voice_turn(result)


if __name__ == "__main__":
    main()
