"""Rule NLU command parsing (Phase 3 engine, Phase 2 command compat)."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.clock import FixedClock
from domain.enums import Intent, TimeWindow, Topic
from nlu.engine import RuleNluEngine


def test_topic_and_time_commands() -> None:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))  # Mon
    nlu = RuleNluEngine(clock=clock)
    r = nlu.parse("topic kyc", "BOOK_TOPIC")
    assert r.topic is Topic.KYC_ONBOARDING

    r = nlu.parse("time monday afternoon", "BOOK_TIME_PREFERENCE")
    assert r.time_window is TimeWindow.AFTERNOON
    assert r.preferred_date_ist is not None

    r = nlu.parse("book new", "INTENT_ROUTING")
    assert r.intent is Intent.BOOK_NEW

    r = nlu.parse("second", "BOOK_OFFER_SLOTS")
    assert r.slot_choice == 2
