"""Prepare orchestrator assistant strings for TTS (IST verbatim; spell codes)."""

from __future__ import annotations

import re

from domain.codes import to_spelling

# Match "Booking code: NL-A742" style lines only — leave IST slot lines untouched.
_BOOKING_CODE_LINE = re.compile(
    r"(?P<prefix>Booking code:\s*)(?P<code>[A-Z]{2}-[A-Z]\d{3})",
    re.IGNORECASE,
)


def prepare_assistant_for_tts(message: str, *, spell_codes: bool = True) -> str:
    """
    TTS readback helper.

    - Confirm / slot IST strings are left verbatim (orchestrator already formatted them).
    - Optionally spell the booking-code token only (Phase 7 exit: code line only).
    """
    if not spell_codes or not message:
        return message

    def _repl(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{to_spelling(match.group('code'))}"

    return _BOOKING_CODE_LINE.sub(_repl, message)
