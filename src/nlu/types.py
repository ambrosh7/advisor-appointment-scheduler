"""Structured NLU result shared by rule and LLM engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.enums import Intent, TimeWindow, Topic


@dataclass
class NluResult:
    intent: Intent = Intent.UNKNOWN
    topic: Optional[Topic] = None
    preferred_date_ist: Optional[date] = None
    time_window: Optional[TimeWindow] = None
    booking_code_guess: Optional[str] = None
    slot_choice: Optional[int] = None  # 1 or 2
    acknowledged_disclaimer: bool = False
    confirmed: bool = False
    wants_investment_advice: bool = False
    confidence: float = 0.0
    raw_text: str = ""
    date_phrase: Optional[str] = None
    needs_clarification: bool = False
    clarification_prompt: Optional[str] = None
    entities: dict = field(default_factory=dict)
