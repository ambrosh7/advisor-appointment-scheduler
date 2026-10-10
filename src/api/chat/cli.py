"""
CLI REPL for demos.

Usage:
  PYTHONPATH=src python -m api.chat
"""

from __future__ import annotations

import logging

from domain.calendar import MockCalendarService
from domain.clock import SystemClock
from integrations.booking_agent.factory import build_phase4_side_effects
from integrations.google_mcp.config import GoogleMcpConfig
from nlu.engine import build_default_nlu_engine
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore

logger = logging.getLogger(__name__)


def _print_turn(messages: list[str], state: str) -> None:
    for msg in messages:
        print(f"\nAssistant [{state}]:\n{msg}")


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
            print(
                "Phase 4–6: Gemini booking + waitlist/cancel/reschedule enabled "
                f"(model={config.gemini_model}, sdk=google.genai)."
            )
        except Exception as exc:  # noqa: BLE001
            print(f"MCP side effects disabled ({exc}). Confirm/waitlist email may fail.")
    else:
        print("MCP side effects disabled: " + "; ".join(errors))

    # Demo CLI uses rule NLU (typed commands). Gemini is used for Phase-4 tool calls.
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
    turn = orch.create_session()
    session = orch.store.get(turn.session_id)
    assert session is not None
    print(f"Session {turn.session_id}")
    _print_turn(turn.messages, turn.state.value)
    print(
        "\nType a message (or /quit). "
        "Flow: yes → book new → topic kyc → time monday afternoon → 1 → confirm"
    )

    while True:
        try:
            text = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not text:
            continue
        if text in {"/quit", "/exit", "quit", "exit"}:
            print("Bye.")
            break
        session = orch.store.get(turn.session_id)
        if session is None:
            print("Session expired. Starting a new one.")
            turn = orch.create_session()
            session = orch.store.get(turn.session_id)
            assert session is not None
            _print_turn(turn.messages, turn.state.value)
            continue
        turn = orch.handle(text, session)
        _print_turn(turn.messages, turn.state.value)


if __name__ == "__main__":
    main()
