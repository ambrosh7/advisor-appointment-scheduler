"""Extract a display full name from a short utterance (not phone/email PII)."""

from __future__ import annotations

import re
from typing import Optional

from nlu.pii import detect_pii

_PREFIX = re.compile(
    r"^\s*(?:my\s+name\s+is|i\s+am|i'm|this\s+is|name\s*[:\-]?)\s+",
    re.I,
)
_WORD = re.compile(r"^[A-Za-z][A-Za-z\-']{0,30}$")
_BLOCKED = {
    "yes",
    "no",
    "ok",
    "okay",
    "confirm",
    "book",
    "cancel",
    "reschedule",
    "understand",
    "hello",
    "hi",
}


def extract_full_name(text: str) -> Optional[str]:
    """
    Return a normalized display name (1–5 words) or None.

    Prefers first+last, but accepts a single given name for voice demos.
    Rejects phone/email/account-like strings and bare acknowledgements.
    """
    raw = (text or "").strip()
    if not raw or detect_pii(raw):
        return None
    cleaned = _PREFIX.sub("", raw).strip(" .,!?;:")
    if not cleaned or detect_pii(cleaned):
        return None
    words = cleaned.split()
    if not (1 <= len(words) <= 5):
        return None
    if any(w.lower() in _BLOCKED for w in words):
        return None
    if not all(_WORD.match(w) for w in words):
        return None
    return " ".join(w[:1].upper() + w[1:] for w in words)
