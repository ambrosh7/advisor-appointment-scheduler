"""Resolver pipeline: relative dates and fuzzy topic mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional
from zoneinfo import ZoneInfo

from domain.clock import Clock, SystemClock
from domain.enums import Topic
from nlu.schema import TOPIC_KEYS, TOPIC_TO_KEY

IST = ZoneInfo("Asia/Kolkata")

_DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# Aliases → topic key for fuzzy / token matching
_TOPIC_ALIASES: dict[str, str] = {
    "kyc": "kyc_onboarding",
    "onboarding": "kyc_onboarding",
    "kyc/onboarding": "kyc_onboarding",
    "kyc onboarding": "kyc_onboarding",
    "sip": "sip_mandates",
    "mandate": "sip_mandates",
    "mandates": "sip_mandates",
    "sip/mandates": "sip_mandates",
    "sip mandates": "sip_mandates",
    "statements": "statements_tax_docs",
    "statement": "statements_tax_docs",
    "tax": "statements_tax_docs",
    "tax docs": "statements_tax_docs",
    "tax documents": "statements_tax_docs",
    "statements/tax docs": "statements_tax_docs",
    "withdrawal": "withdrawals_timelines",
    "withdrawals": "withdrawals_timelines",
    "timeline": "withdrawals_timelines",
    "timelines": "withdrawals_timelines",
    "withdrawals & timelines": "withdrawals_timelines",
    "account": "account_changes_nominee",
    "account changes": "account_changes_nominee",
    "nominee": "account_changes_nominee",
    "account changes/nominee": "account_changes_nominee",
}


@dataclass(frozen=True)
class DateResolveResult:
    resolved: Optional[date]
    needs_clarification: bool
    phrase: Optional[str] = None


@dataclass(frozen=True)
class TopicMapResult:
    topic: Optional[Topic]
    key: Optional[str]
    score: float
    needs_clarification: bool


class RelativeDateResolver:
    """``date_phrase`` + today (IST) → LocalDate or needs_clarification."""

    def __init__(self, clock: Optional[Clock] = None) -> None:
        self._clock = clock or SystemClock()

    def today_ist(self) -> date:
        return self._clock.now().astimezone(IST).date()

    def resolve(self, date_phrase: Optional[str]) -> DateResolveResult:
        if not date_phrase or not str(date_phrase).strip():
            return DateResolveResult(resolved=None, needs_clarification=False, phrase=date_phrase)

        text = str(date_phrase).strip()
        lower = text.lower()
        today = self.today_ist()

        if re.search(r"\btoday\b", lower):
            return DateResolveResult(resolved=today, needs_clarification=False, phrase=text)
        if re.search(r"\btomorrow\b", lower):
            return DateResolveResult(
                resolved=today + timedelta(days=1),
                needs_clarification=False,
                phrase=text,
            )

        iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
        if iso:
            try:
                return DateResolveResult(
                    resolved=date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))),
                    needs_clarification=False,
                    phrase=text,
                )
            except ValueError:
                return DateResolveResult(resolved=None, needs_clarification=True, phrase=text)

        # "8 April 2026" / "April 8"
        mdy = re.search(
            r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+(20\d{2})\b",
            lower,
        )
        if mdy:
            months = {
                "january": 1,
                "february": 2,
                "march": 3,
                "april": 4,
                "may": 5,
                "june": 6,
                "july": 7,
                "august": 8,
                "september": 9,
                "october": 10,
                "november": 11,
                "december": 12,
            }
            try:
                return DateResolveResult(
                    resolved=date(int(mdy.group(3)), months[mdy.group(2)], int(mdy.group(1))),
                    needs_clarification=False,
                    phrase=text,
                )
            except ValueError:
                return DateResolveResult(resolved=None, needs_clarification=True, phrase=text)

        for name, weekday in _DAY_NAMES.items():
            if re.search(rf"\b{name}\b", lower):
                delta = (weekday - today.weekday()) % 7
                if delta == 0:
                    if re.search(rf"\bthis\s+{name}\b", lower):
                        return DateResolveResult(resolved=today, needs_clarification=False, phrase=text)
                    delta = 7
                return DateResolveResult(
                    resolved=today + timedelta(days=delta),
                    needs_clarification=False,
                    phrase=text,
                )

        # Vague relative phrases that need clarification
        if re.search(r"\b(?:next week|sometime|soon|later|whenever)\b", lower):
            return DateResolveResult(resolved=None, needs_clarification=True, phrase=text)

        # Non-empty but unparsed
        if re.search(r"\b(?:day|date|on)\b", lower) or len(text.split()) >= 1:
            # If it looks like an attempt at a date but we failed → clarify
            if re.search(r"\d", text) or re.search(r"\b(?:next|this|on)\b", lower):
                return DateResolveResult(resolved=None, needs_clarification=True, phrase=text)

        return DateResolveResult(resolved=None, needs_clarification=False, phrase=text)


class TopicMapper:
    """Fuzzy match user text / topic key to closed ``Topic`` enum."""

    def __init__(self, threshold: float = 0.72) -> None:
        self._threshold = threshold
        self._labels: list[tuple[str, str]] = []
        for key, topic in TOPIC_KEYS.items():
            self._labels.append((key, key))
            self._labels.append((topic.value.lower(), key))
            self._labels.append((TOPIC_TO_KEY[topic].replace("_", " "), key))
        for alias, key in _TOPIC_ALIASES.items():
            self._labels.append((alias, key))

    def map_key(self, topic_key: Optional[str]) -> TopicMapResult:
        if not topic_key:
            return TopicMapResult(topic=None, key=None, score=0.0, needs_clarification=False)
        key = topic_key.strip().lower()
        if key in TOPIC_KEYS:
            return TopicMapResult(
                topic=TOPIC_KEYS[key], key=key, score=1.0, needs_clarification=False
            )
        return self.map_text(topic_key)

    def map_text(self, text: str) -> TopicMapResult:
        if not text or not text.strip():
            return TopicMapResult(topic=None, key=None, score=0.0, needs_clarification=False)

        cleaned = text.strip().lower()
        # Strip stub command prefix
        cleaned = re.sub(r"^\s*topic\s+", "", cleaned)

        # Multiple distinct topic aliases in one utterance → ask which of five
        alias_hits = {
            key
            for alias, key in _TOPIC_ALIASES.items()
            if re.search(rf"\b{re.escape(alias)}\b", cleaned)
        }
        if len(alias_hits) >= 2:
            return TopicMapResult(
                topic=None, key=None, score=0.5, needs_clarification=True
            )

        if cleaned in _TOPIC_ALIASES:
            key = _TOPIC_ALIASES[cleaned]
            return TopicMapResult(
                topic=TOPIC_KEYS[key], key=key, score=1.0, needs_clarification=False
            )
        if cleaned in TOPIC_KEYS:
            return TopicMapResult(
                topic=TOPIC_KEYS[cleaned], key=cleaned, score=1.0, needs_clarification=False
            )

        best_key: Optional[str] = None
        best_score = 0.0
        second = 0.0
        for label, key in self._labels:
            score = SequenceMatcher(None, cleaned, label).ratio()
            # Bonus for substring / token containment
            if label in cleaned or cleaned in label:
                score = max(score, 0.9)
            if score > best_score:
                second = best_score
                best_score = score
                best_key = key
            elif score > second:
                second = score

        # Ambiguous: two close high scores for different keys
        if best_key and best_score >= self._threshold:
            # Recalculate if another key is within 0.05
            competing = False
            for label, key in self._labels:
                if key == best_key:
                    continue
                score = SequenceMatcher(None, cleaned, label).ratio()
                if label in cleaned or cleaned in label:
                    score = max(score, 0.9)
                if score >= self._threshold and abs(score - best_score) <= 0.05:
                    competing = True
                    break
            if competing:
                return TopicMapResult(
                    topic=None, key=None, score=best_score, needs_clarification=True
                )
            return TopicMapResult(
                topic=TOPIC_KEYS[best_key],
                key=best_key,
                score=best_score,
                needs_clarification=False,
            )

        if cleaned and best_score > 0.4:
            # User tried to name a topic but below threshold
            return TopicMapResult(
                topic=None, key=None, score=best_score, needs_clarification=True
            )

        return TopicMapResult(
            topic=None, key=None, score=best_score, needs_clarification=False
        )
