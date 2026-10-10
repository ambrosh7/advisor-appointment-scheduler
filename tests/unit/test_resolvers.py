"""RelativeDateResolver and TopicMapper."""

from __future__ import annotations

from datetime import date, datetime, timezone

from domain.clock import FixedClock
from domain.enums import Topic
from nlu.resolvers import RelativeDateResolver, TopicMapper
from nlu.schema import TOPIC_TO_KEY


def test_relative_date_today_tomorrow_weekday() -> None:
    # Monday 6 Apr 2026 IST (~02:00 UTC)
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    r = RelativeDateResolver(clock)
    assert r.today_ist() == date(2026, 4, 6)
    assert r.resolve("today").resolved == date(2026, 4, 6)
    assert r.resolve("tomorrow").resolved == date(2026, 4, 7)
    assert r.resolve("friday").resolved == date(2026, 4, 10)
    assert r.resolve("monday").resolved == date(2026, 4, 13)  # next week
    assert r.resolve("this monday").resolved == date(2026, 4, 6)
    assert r.resolve("2026-04-08").resolved == date(2026, 4, 8)


def test_relative_date_needs_clarification() -> None:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    r = RelativeDateResolver(clock)
    assert r.resolve("sometime next week").needs_clarification is True
    assert r.resolve("on the 99th of Never 2026").needs_clarification is True


def test_topic_mapper_exact_and_alias() -> None:
    m = TopicMapper()
    assert m.map_key("kyc_onboarding").topic is Topic.KYC_ONBOARDING
    assert m.map_text("KYC").topic is Topic.KYC_ONBOARDING
    assert m.map_text("tax docs").topic is Topic.STATEMENTS_TAX_DOCS
    assert m.map_text("nominee").topic is Topic.ACCOUNT_CHANGES_NOMINEE
    assert TOPIC_TO_KEY[Topic.SIP_MANDATES] == "sip_mandates"


def test_topic_mapper_ambiguous_multi_alias() -> None:
    m = TopicMapper()
    result = m.map_text("I need help with SIP and nominee changes")
    assert result.topic is None
    assert result.needs_clarification is True
