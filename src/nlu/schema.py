"""Structured extraction schema (JSON / tool-call shape) for NLU."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from domain.enums import Intent, TimeWindow, Topic

# Snake_case keys used in LLM JSON ↔ Topic enum
TOPIC_KEYS: dict[str, Topic] = {
    "kyc_onboarding": Topic.KYC_ONBOARDING,
    "sip_mandates": Topic.SIP_MANDATES,
    "statements_tax_docs": Topic.STATEMENTS_TAX_DOCS,
    "withdrawals_timelines": Topic.WITHDRAWALS_TIMELINES,
    "account_changes_nominee": Topic.ACCOUNT_CHANGES_NOMINEE,
}

TOPIC_TO_KEY: dict[Topic, str] = {v: k for k, v in TOPIC_KEYS.items()}

INTENT_VALUES = {i.value for i in Intent}
TIME_WINDOW_VALUES = {w.value for w in TimeWindow if w is not TimeWindow.EXACT}


@dataclass
class StructuredExtraction:
    """Forced JSON shape from rules or LLM (before resolvers)."""

    intent: str = "unknown"
    topic: Optional[str] = None  # snake_case key or null
    date_phrase: Optional[str] = None
    time_window: Optional[str] = None  # morning|afternoon|evening|null
    booking_code_guess: Optional[str] = None
    wants_investment_advice: bool = False
    confidence: float = 0.0
    # Dialogue acts used by the orchestrator (optional in LLM JSON)
    slot_choice: Optional[int] = None
    acknowledged_disclaimer: bool = False
    confirmed: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "topic": self.topic,
            "date_phrase": self.date_phrase,
            "time_window": self.time_window,
            "booking_code_guess": self.booking_code_guess,
            "wants_investment_advice": self.wants_investment_advice,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredExtraction":
        intent = str(data.get("intent") or "unknown").strip().lower()
        if intent not in INTENT_VALUES:
            intent = "unknown"

        topic_raw = data.get("topic")
        topic: Optional[str] = None
        if topic_raw is not None and str(topic_raw).strip().lower() not in ("", "null", "none"):
            key = str(topic_raw).strip().lower().replace(" ", "_").replace("/", "_")
            # Accept enum values too
            if key in TOPIC_KEYS:
                topic = key
            else:
                for k, t in TOPIC_KEYS.items():
                    if key == t.value.lower().replace(" ", "_").replace("/", "_").replace("&", "and"):
                        topic = k
                        break
                else:
                    topic = key  # leave for TopicMapper fuzzy path via date_phrase-like handling

        window_raw = data.get("time_window")
        time_window: Optional[str] = None
        if window_raw is not None and str(window_raw).strip().lower() not in ("", "null", "none"):
            w = str(window_raw).strip().lower()
            time_window = w if w in TIME_WINDOW_VALUES else None

        conf = data.get("confidence", 0.0)
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        slot_choice = data.get("slot_choice")
        if slot_choice is not None:
            try:
                slot_choice = int(slot_choice)
                if slot_choice not in (1, 2):
                    slot_choice = None
            except (TypeError, ValueError):
                slot_choice = None

        date_phrase = data.get("date_phrase")
        if date_phrase is not None:
            date_phrase = str(date_phrase).strip() or None

        code = data.get("booking_code_guess")
        if code is not None:
            code = str(code).strip() or None

        return cls(
            intent=intent,
            topic=topic,
            date_phrase=date_phrase,
            time_window=time_window,
            booking_code_guess=code,
            wants_investment_advice=bool(data.get("wants_investment_advice", False)),
            confidence=confidence,
            slot_choice=slot_choice,
            acknowledged_disclaimer=bool(data.get("acknowledged_disclaimer", False)),
            confirmed=bool(data.get("confirmed", False)),
        )


def topic_enum(key: Optional[str]) -> Optional[Topic]:
    if not key:
        return None
    return TOPIC_KEYS.get(key.strip().lower())
