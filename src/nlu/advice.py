"""Investment-advice refusal gate (keyword path)."""

from __future__ import annotations

import os
import re
from typing import Optional

_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"\binvest(?:ment|ing)?\b",
        r"\bwhich\s+fund\b",
        r"\bstock\s+tip",
        r"\bbuy\s+(?:or\s+sell|stocks?|shares?)\b",
        r"\bportfolio\s+advice\b",
        r"\bshould\s+i\s+(?:buy|sell|invest)\b",
        r"\breturns?\s+guarantee",
        r"\bmarket\s+tip",
    ]
]

_DEFAULT_EDUCATIONAL_URL = "https://example.com/learn/basics"


def educational_url(override: Optional[str] = None) -> str:
    if override is not None and override.strip():
        return override.strip()
    return (
        (os.getenv("ADVICE_EDUCATIONAL_URL") or "").strip() or _DEFAULT_EDUCATIONAL_URL
    )


def advice_refusal_message(url: Optional[str] = None) -> str:
    link = educational_url(url)
    return (
        "I can’t provide investment advice — this assistant is informational only. "
        f"For educational reading you can start here: {link}. "
        "If you’d like, I can help you book a tentative advisor slot instead."
    )


# Back-compat for imports that expect a module-level constant.
ADVICE_REFUSAL_MESSAGE = advice_refusal_message()


def detect_investment_advice(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _PATTERNS)
