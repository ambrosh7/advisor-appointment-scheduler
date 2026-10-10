"""Extractors that produce StructuredExtraction (rules or LLM)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional, Protocol

from domain.enums import Intent
from nlu.advice import detect_investment_advice
from nlu.prompts import SYSTEM_PROMPT, build_user_prompt
from nlu.schema import StructuredExtraction
from nlu.resolvers import TopicMapper

# Voice STT often returns "yes i understand" as one phrase — allow combos.
_ACK = re.compile(
    r"^\s*(?:"
    r"(?:yes|y|ok|okay)(?:\s*,?\s*(?:i\s+understand|understood|agree|acknowledged))?"
    r"|i\s+understand|understood|agree|acknowledged"
    r")\s*[.!?]?\s*$",
    re.I,
)
_CONFIRM = re.compile(
    r"^\s*(?:yes|y|ok|okay|confirm(?:ed)?|proceed|book\s+it|sounds?\s+good)\s*[.!?]?\s*$",
    re.I,
)
_BOOK_NEW = re.compile(
    r"\b(?:book\s+new|new\s+booking|schedule|make\s+an?\s+appointment|"
    r"book\s+an?\s+(?:advisor\s+)?(?:slot|appointment))\b",
    re.I,
)
# Bare "book" only when not an availability question
_BOOK_BARE = re.compile(r"\bbook\b", re.I)
_RESCHEDULE = re.compile(r"\breschedule\b", re.I)
_CANCEL = re.compile(r"\bcancel\b", re.I)
_PREPARE = re.compile(r"\b(?:what\s+to\s+prepare|prepare(?:\s+for\s+(?:the\s+)?(?:call|meeting))?|checklist)\b", re.I)
_AVAIL = re.compile(
    r"\b(?:availability|when\s+can\s+i\s+book|available\s+slots?|check\s+availability)\b",
    re.I,
)
_SLOT_CHOICE = re.compile(
    r"^\s*(?:(?:slot\s*)?(?P<n>[12])|(?P<word>first|second|1st|2nd))\s*[.!?]?\s*$",
    re.I,
)
_TIME_CMD = re.compile(r"^\s*time\s+(.+)$", re.I)
_WINDOW = re.compile(r"\b(morning|afternoon|evening)\b", re.I)
_CODE = re.compile(r"\b([A-Z]{2}-[A-Z]\d{3})\b", re.I)


class StructuredExtractor(Protocol):
    def extract(
        self,
        transcript: str,
        state: str,
        last_assistant_question: str = "",
    ) -> StructuredExtraction: ...


class RuleExtractor:
    """Keyword + regex router (Phase 3 LLM-free shortcut)."""

    def __init__(self) -> None:
        self._topic_mapper = TopicMapper()

    def extract(
        self,
        transcript: str,
        state: str,
        last_assistant_question: str = "",
    ) -> StructuredExtraction:
        _ = last_assistant_question
        text = (transcript or "").strip()
        ext = StructuredExtraction(confidence=0.5)

        if not text:
            ext.confidence = 0.0
            return ext

        if detect_investment_advice(text):
            ext.wants_investment_advice = True
            ext.confidence = 0.9
            return ext

        if _ACK.match(text):
            ext.acknowledged_disclaimer = True
            ext.confirmed = True
            ext.confidence = 0.95

        if _CONFIRM.match(text):
            ext.confirmed = True
            ext.confidence = max(ext.confidence, 0.9)

        slot_m = _SLOT_CHOICE.match(text)
        if slot_m:
            if slot_m.group("n"):
                ext.slot_choice = int(slot_m.group("n"))
            else:
                word = slot_m.group("word").lower()
                ext.slot_choice = 1 if word in ("first", "1st") else 2
            ext.confidence = 0.95

        code_m = _CODE.search(text)
        if code_m:
            ext.booking_code_guess = code_m.group(1).upper()
            ext.confidence = max(ext.confidence, 0.8)

        # Topic from dedicated mapper (fuzzy)
        topic_body = re.sub(r"^\s*topic\s+", "", text, flags=re.I)
        mapped = self._topic_mapper.map_text(topic_body)
        if mapped.key:
            ext.topic = mapped.key
            ext.confidence = max(ext.confidence, mapped.score)
        elif mapped.needs_clarification:
            # Signal ambiguity via low-confidence topic attempt
            ext.topic = None
            ext.confidence = min(ext.confidence, mapped.score if mapped.score else 0.4)

        time_body = text
        time_m = _TIME_CMD.match(text)
        if time_m:
            time_body = time_m.group(1).strip()

        win = _WINDOW.search(time_body)
        if win:
            ext.time_window = win.group(1).lower()
            ext.confidence = max(ext.confidence, 0.8)

        # Keep raw phrase for RelativeDateResolver
        if time_m or win or re.search(
            r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|"
            r"saturday|sunday|next\s+week|20\d{2}-\d{2}-\d{2})\b",
            time_body,
            re.I,
        ):
            ext.date_phrase = time_body
            ext.confidence = max(ext.confidence, 0.75)

        # Availability before bare "book" so "when can I book" does not become book_new
        if _AVAIL.search(text):
            ext.intent = Intent.CHECK_AVAILABILITY.value
            ext.confidence = max(ext.confidence, 0.85)
        elif _RESCHEDULE.search(text):
            ext.intent = Intent.RESCHEDULE.value
            ext.confidence = max(ext.confidence, 0.85)
        elif _CANCEL.search(text):
            ext.intent = Intent.CANCEL.value
            ext.confidence = max(ext.confidence, 0.85)
        elif _PREPARE.search(text):
            ext.intent = Intent.WHAT_TO_PREPARE.value
            ext.confidence = max(ext.confidence, 0.85)
        elif _BOOK_NEW.search(text) or (
            _BOOK_BARE.search(text) and not re.search(r"\bwhen\b", text, re.I)
        ):
            ext.intent = Intent.BOOK_NEW.value
            ext.confidence = max(ext.confidence, 0.85)

        state_u = (state or "").upper()
        if ext.intent == Intent.UNKNOWN.value:
            if state_u == "BOOK_TOPIC" and ext.topic:
                ext.intent = Intent.BOOK_NEW.value
            elif state_u == "BOOK_TIME_PREFERENCE" and (ext.time_window or ext.date_phrase):
                ext.intent = Intent.BOOK_NEW.value
            elif state_u == "INTENT_ROUTING" and ext.topic:
                ext.intent = Intent.BOOK_NEW.value

        return ext


class LlmExtractor:
    """
    LLM JSON extractor (Gemini by default).

    Falls back to ``RuleExtractor`` when no API key is configured or the call fails.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "gemini-3.8-flash",
        fallback: Optional[RuleExtractor] = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self._model = model
        self._fallback = fallback or RuleExtractor()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def extract(
        self,
        transcript: str,
        state: str,
        last_assistant_question: str = "",
    ) -> StructuredExtraction:
        if not self._api_key:
            return self._fallback.extract(transcript, state, last_assistant_question)

        try:
            raw = self._call_gemini(transcript, state, last_assistant_question)
            data = _parse_json_object(raw)
            ext = StructuredExtraction.from_dict(data)
            # Rules own clear yes/ack phrases — LLM often leaves these false
            # (prompt says disclaimer is orchestrator-owned).
            rules = self._fallback.extract(transcript, state, last_assistant_question)
            if rules.acknowledged_disclaimer:
                ext.acknowledged_disclaimer = True
            if rules.confirmed:
                ext.confirmed = True
            return ext
        except Exception:
            return self._fallback.extract(transcript, state, last_assistant_question)

    def _call_gemini(self, transcript: str, state: str, last_q: str) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("google-genai not installed") from exc

        client = genai.Client(api_key=self._api_key)
        user = build_user_prompt(transcript, state, last_q)
        response = client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data
