"""PII firewall — regex heuristics; no persistence of matched values."""

from __future__ import annotations

import re

# Phone (IN-ish / general) and email — do not capture groups into logs upstream.
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_PHONE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]*)?\d{3,5}[-.\s]?\d{4,5}"
    r"|\b\d{10}\b"
)
# Account-like long digit runs (8+) that are not already handled as phones
_ACCOUNT = re.compile(r"(?<!\d)\d{8,}(?!\d)")

DEFAULT_SECURE_URL = "https://example.com/complete"

PII_REDIRECT_MESSAGE = (
    "I can’t take phone numbers, email addresses, or account details on this chat. "
    "Please use the secure link after booking to share contact details: "
    f"{DEFAULT_SECURE_URL}"
)


def detect_pii(text: str) -> bool:
    if not text:
        return False
    return bool(_EMAIL.search(text) or _PHONE.search(text) or _ACCOUNT.search(text))
