"""TTS prepare: IST untouched; booking code spelled."""

from __future__ import annotations

import pytest

from domain.codes import to_spelling
from integrations.voice.prepare import prepare_assistant_for_tts

pytestmark = pytest.mark.voice


def test_spells_booking_code_line_only() -> None:
    msg = (
        "You’re booked tentatively.\n"
        "• Booking code: NL-A742\n"
        "• Slot: Monday, 6 April 2026, 1:00 PM IST\n"
    )
    spoken = prepare_assistant_for_tts(msg)
    assert to_spelling("NL-A742") in spoken
    assert "Monday, 6 April 2026, 1:00 PM IST" in spoken
    assert "NL-A742" not in spoken  # replaced by spelling


def test_spell_codes_off_keeps_raw() -> None:
    msg = "• Booking code: NL-A742\n"
    assert prepare_assistant_for_tts(msg, spell_codes=False) == msg
