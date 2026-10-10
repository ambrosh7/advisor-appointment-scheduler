"""Static prepare snippets — closed Topic map, no LLM."""

from __future__ import annotations

from domain.enums import Topic
from session.prepare import GENERIC_PREPARE, prepare_snippet


def test_every_topic_has_snippet() -> None:
    for topic in Topic:
        text = prepare_snippet(topic)
        assert topic.value.split("/")[0].lower() in text.lower() or "prepare" in text.lower()
        assert len(text) > 40


def test_generic_lists_topics() -> None:
    assert "KYC Onboarding" in GENERIC_PREPARE
    assert "SIP Mandates" in GENERIC_PREPARE
