"""Ambiguous topic / low-confidence clarification (Phase 3)."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from nlu.engine import RuleNluEngine
from nlu.policy import CLARIFY_TOPIC, IntentPolicy
from session.orchestrator import Orchestrator
from session.states import State
from session.store import InMemorySessionStore


def test_ambiguous_topic_triggers_which_of_five() -> None:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
    )
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    orch.handle("yes", session)
    orch.handle("Ambrosh Patel", session)
    orch.handle("book new", session)
    assert session.state is State.BOOK_TOPIC

    turn = orch.handle("I need help with SIP and nominee changes", session)
    assert session.state is State.BOOK_TOPIC  # did not advance
    assert any("Which of these five" in m for m in turn.messages)


def test_intent_policy_caps_clarifications() -> None:
    policy = IntentPolicy(threshold=0.9, max_per_state=2)
    counts: dict = {}
    d1 = policy.decide(
        state="INTENT_ROUTING",
        confidence=0.1,
        clarification_counts=counts,
        intent_unknown=True,
    )
    d2 = policy.decide(
        state="INTENT_ROUTING",
        confidence=0.1,
        clarification_counts=counts,
        intent_unknown=True,
    )
    d3 = policy.decide(
        state="INTENT_ROUTING",
        confidence=0.1,
        clarification_counts=counts,
        intent_unknown=True,
    )
    assert d1.needs_clarification and d2.needs_clarification
    assert d3.needs_clarification is False
    assert d3.reason == "intent_cap_reached"


def test_engine_sets_clarification_prompt_for_topic() -> None:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    engine = RuleNluEngine(clock=clock)

    class Ctx:
        last_assistant_question = "Which topic?"
        clarification_counts: dict = {}

    result = engine.parse(
        "SIP and nominee together",
        "BOOK_TOPIC",
        Ctx(),
    )
    assert result.needs_clarification is True
    assert result.clarification_prompt == CLARIFY_TOPIC
