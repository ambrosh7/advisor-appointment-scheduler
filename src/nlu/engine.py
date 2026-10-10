"""
NluEngine: extract → resolve → policy → NluResult.

``RuleNluEngine`` is the default (no network). ``LlmNluEngine`` uses Gemini when
``GEMINI_API_KEY`` is set, otherwise identical to rules.
"""

from __future__ import annotations

from typing import Optional, Protocol

from domain.clock import Clock, SystemClock
from domain.enums import Intent, TimeWindow
from nlu.extractors import LlmExtractor, RuleExtractor, StructuredExtractor
from nlu.policy import IntentPolicy
from nlu.resolvers import RelativeDateResolver, TopicMapper
from nlu.schema import StructuredExtraction, topic_enum
from nlu.types import NluResult


class NluEngine(Protocol):
    def parse(self, transcript: str, state: str, context: object = None) -> NluResult: ...


class PipelineNluEngine:
    """Full Phase 3 pipeline behind the stable ``parse`` interface."""

    def __init__(
        self,
        extractor: Optional[StructuredExtractor] = None,
        *,
        clock: Optional[Clock] = None,
        date_resolver: Optional[RelativeDateResolver] = None,
        topic_mapper: Optional[TopicMapper] = None,
        policy: Optional[IntentPolicy] = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._extractor = extractor or RuleExtractor()
        self._dates = date_resolver or RelativeDateResolver(self._clock)
        self._topics = topic_mapper or TopicMapper()
        self._policy = policy or IntentPolicy()

    def parse(self, transcript: str, state: str, context: object = None) -> NluResult:
        last_q = ""
        clarification_counts: dict = {}
        if context is not None:
            last_q = getattr(context, "last_assistant_question", "") or ""
            counts = getattr(context, "clarification_counts", None)
            if isinstance(counts, dict):
                clarification_counts = counts

        ext = self._extractor.extract(transcript, state, last_q)
        return self._to_result(ext, state, transcript, clarification_counts)

    def _to_result(
        self,
        ext: StructuredExtraction,
        state: str,
        transcript: str,
        clarification_counts: dict,
    ) -> NluResult:
        result = NluResult(
            raw_text=transcript,
            confidence=ext.confidence,
            wants_investment_advice=ext.wants_investment_advice,
            booking_code_guess=ext.booking_code_guess,
            slot_choice=ext.slot_choice,
            acknowledged_disclaimer=ext.acknowledged_disclaimer,
            confirmed=ext.confirmed,
            date_phrase=ext.date_phrase,
            entities={
                "structured": ext.to_json_dict(),
            },
        )

        try:
            result.intent = Intent(ext.intent)
        except ValueError:
            result.intent = Intent.UNKNOWN

        state_u = (state or "").upper()
        secondary_intent = result.intent in {
            Intent.RESCHEDULE,
            Intent.CANCEL,
            Intent.WHAT_TO_PREPARE,
            Intent.CHECK_AVAILABILITY,
        }

        # Topic: prefer structured key, else fuzzy on transcript when in topic states.
        # Skip fuzzy topic nags when a secondary intent is already clear (e.g. "cancel"
        # otherwise fuzzy-matches a topic label and blocks routing).
        topic_map = self._topics.map_key(ext.topic)
        topic_needs = topic_map.needs_clarification
        if (
            topic_map.topic is None
            and not secondary_intent
            and state_u
            in {
                "BOOK_TOPIC",
                "INTENT_ROUTING",
                "PREPARE_TOPIC_OR_GENERIC",
            }
        ):
            # Re-map raw transcript for natural phrases ("I need help with KYC")
            fuzzy = self._topics.map_text(transcript)
            if fuzzy.topic is not None:
                topic_map = fuzzy
            topic_needs = topic_needs or fuzzy.needs_clarification

        result.topic = topic_map.topic
        if topic_map.key:
            result.entities["topic_key"] = topic_map.key

        # Time window
        if ext.time_window:
            try:
                result.time_window = TimeWindow(ext.time_window)
            except ValueError:
                result.time_window = None

        # Date
        date_res = self._dates.resolve(ext.date_phrase)
        result.preferred_date_ist = date_res.resolved
        date_needs = date_res.needs_clarification

        # Intent policy clarifications
        intent_unknown = result.intent is Intent.UNKNOWN and not (
            result.acknowledged_disclaimer
            or result.confirmed
            or result.slot_choice
            or result.topic
            or result.time_window
            or result.preferred_date_ist
            or result.booking_code_guess
        )

        if secondary_intent and state_u == "INTENT_ROUTING":
            topic_needs = False

        # Ambiguous topic while collecting topic
        if state_u == "BOOK_TOPIC" and topic_needs and result.topic is None:
            topic_needs = True
        elif state_u == "BOOK_TOPIC" and result.topic is None and transcript.strip():
            # Non-empty utterance that didn't map — ask which of five
            if not result.acknowledged_disclaimer and not result.slot_choice:
                fuzzy = self._topics.map_text(transcript)
                if fuzzy.needs_clarification or fuzzy.score > 0.3:
                    topic_needs = True

        decision = self._policy.decide(
            state=state_u,
            confidence=result.confidence,
            clarification_counts=clarification_counts,
            topic_needs_clarification=topic_needs and result.topic is None,
            date_needs_clarification=date_needs and state_u == "BOOK_TIME_PREFERENCE",
            intent_unknown=intent_unknown and state_u == "INTENT_ROUTING",
        )

        if decision.needs_clarification:
            result.needs_clarification = True
            result.clarification_prompt = decision.clarification_prompt

        return result


def build_default_nlu_engine(
    clock: Optional[Clock] = None,
    *,
    use_llm: Optional[bool] = None,
) -> PipelineNluEngine:
    """
    Factory used by API/CLI.

    ``use_llm=True`` or ``GEMINI_API_KEY`` set → LLM extractor with rule fallback.
    """
    import os

    clock = clock or SystemClock()
    want_llm = use_llm if use_llm is not None else bool(os.getenv("GEMINI_API_KEY"))
    extractor: StructuredExtractor
    if want_llm:
        model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
        extractor = LlmExtractor(model=model)
    else:
        extractor = RuleExtractor()
    return PipelineNluEngine(extractor=extractor, clock=clock)


# Backward-compatible name used by Phase 2 tests / imports
class RuleNluEngine(PipelineNluEngine):
    def __init__(self, clock: Optional[Clock] = None) -> None:
        super().__init__(extractor=RuleExtractor(), clock=clock)


class StubNluEngine(RuleNluEngine):
    """Alias kept for Phase 2 import paths."""
