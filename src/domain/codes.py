"""Booking code generation and TTS spelling helpers."""

from __future__ import annotations

import random
import re
from typing import Optional, Protocol

CODE_PATTERN = re.compile(r"^[A-Z]{2}-[A-Z][0-9]{3}$")
DEFAULT_MAX_RETRIES = 5

_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}


class CodeExists(Protocol):
    def exists(self, code: str) -> bool: ...


class BookingCodeGenerator:
    """Generate human-readable codes matching ``[A-Z]{2}-[A-Z][0-9]{3}``."""

    def __init__(
        self,
        store: Optional[CodeExists] = None,
        *,
        seed: Optional[int] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        pattern: re.Pattern[str] = CODE_PATTERN,
    ) -> None:
        self._store = store
        self._rng = random.Random(seed)
        self._max_retries = max_retries
        self._pattern = pattern

    def generate(self) -> str:
        last: Optional[str] = None
        for _ in range(self._max_retries):
            code = self._draw()
            last = code
            if self._store is None or not self._store.exists(code):
                return code
        raise RuntimeError(
            f"Unable to generate unique booking code after {self._max_retries} attempts "
            f"(last={last!r})"
        )

    def _draw(self) -> str:
        prefix = "".join(self._rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=2))
        letter = self._rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        digits = "".join(self._rng.choices("0123456789", k=3))
        code = f"{prefix}-{letter}{digits}"
        if not self._pattern.match(code):
            raise RuntimeError(f"Generated code failed pattern check: {code}")
        return code


def to_spelling(code: str) -> str:
    """Spell a booking code for TTS, e.g. ``NL-A742`` → ``N L dash A seven four two``."""
    parts: list[str] = []
    for ch in code.upper():
        if ch == "-":
            parts.append("dash")
        elif ch.isdigit():
            parts.append(_DIGIT_WORDS[ch])
        elif ch.isalpha():
            parts.append(ch)
        else:
            parts.append(ch)
    return " ".join(parts)
