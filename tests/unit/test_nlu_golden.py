"""Golden text fixtures for each intent label (Phase 3 exit criterion)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.clock import FixedClock
from datetime import datetime, timezone
from nlu.engine import RuleNluEngine
from nlu.schema import TOPIC_TO_KEY

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nlu_golden.json"


@pytest.fixture
def engine() -> RuleNluEngine:
    return RuleNluEngine(clock=FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc)))


@pytest.mark.parametrize("case", json.loads(FIXTURES.read_text()), ids=lambda c: c["id"])
def test_golden_intent_labels(engine: RuleNluEngine, case: dict) -> None:
    result = engine.parse(case["transcript"], case["state"])
    if "expected_intent" in case:
        assert result.intent.value == case["expected_intent"]
    if "expected_topic_key" in case:
        assert result.topic is not None
        assert TOPIC_TO_KEY[result.topic] == case["expected_topic_key"]
