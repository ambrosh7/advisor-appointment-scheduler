"""Intent confidence policy — clarification with per-state cap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, MutableMapping, Optional

DEFAULT_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_MAX_CLARIFICATIONS = 2

CLARIFY_INTENT = (
    "I didn’t catch that clearly — would you like to book a new slot, reschedule, "
    "cancel, ask what to prepare, or check availability?"
)

CLARIFY_TOPIC = (
    "Which of these five topics is this about?\n"
    "• KYC Onboarding\n"
    "• SIP Mandates\n"
    "• Statements/Tax Docs\n"
    "• Withdrawals & Timelines\n"
    "• Account Changes/Nominee"
)

CLARIFY_DATE = (
    "I wasn’t sure about the day. Please share a date in IST — "
    "e.g. “monday”, “tomorrow”, or “2026-04-10”."
)


@dataclass
class PolicyDecision:
    needs_clarification: bool = False
    clarification_prompt: Optional[str] = None
    reason: Optional[str] = None


class IntentPolicy:
    """
    If confidence < τ → one targeted clarification.
    Cap N clarifications per state (tracked on the session mapping).
    """

    def __init__(
        self,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_per_state: int = DEFAULT_MAX_CLARIFICATIONS,
    ) -> None:
        self.threshold = threshold
        self.max_per_state = max_per_state

    def decide(
        self,
        *,
        state: str,
        confidence: float,
        clarification_counts: MutableMapping[str, int],
        topic_needs_clarification: bool = False,
        date_needs_clarification: bool = False,
        intent_unknown: bool = False,
        force_prompt: Optional[str] = None,
    ) -> PolicyDecision:
        state_key = (state or "").upper()

        # Topic / date clarifications are targeted and always honored (subject to cap)
        if topic_needs_clarification:
            return self._maybe_clarify(
                state_key, clarification_counts, force_prompt or CLARIFY_TOPIC, "topic"
            )
        if date_needs_clarification:
            return self._maybe_clarify(
                state_key, clarification_counts, force_prompt or CLARIFY_DATE, "date"
            )

        if confidence >= self.threshold and not intent_unknown:
            return PolicyDecision()

        # Low confidence / unknown intent at routing
        if state_key in {
            "INTENT_ROUTING",
            "GREET",
            "DISCLAIMER_AWAIT_ACK",
            "COLLECT_NAME",
        }:
            if intent_unknown or confidence < self.threshold:
                # Don't nag during disclaimer/name waits for low-confidence "yes" handling
                if state_key in {"DISCLAIMER_AWAIT_ACK", "COLLECT_NAME"}:
                    return PolicyDecision()
                return self._maybe_clarify(
                    state_key, clarification_counts, CLARIFY_INTENT, "intent"
                )

        if confidence < self.threshold and state_key == "BOOK_TOPIC":
            return self._maybe_clarify(
                state_key, clarification_counts, CLARIFY_TOPIC, "topic_low_conf"
            )

        return PolicyDecision()

    def _maybe_clarify(
        self,
        state_key: str,
        counts: MutableMapping[str, int],
        prompt: str,
        reason: str,
    ) -> PolicyDecision:
        used = counts.get(state_key, 0)
        if used >= self.max_per_state:
            return PolicyDecision(
                needs_clarification=False,
                clarification_prompt=None,
                reason=f"{reason}_cap_reached",
            )
        counts[state_key] = used + 1
        return PolicyDecision(
            needs_clarification=True,
            clarification_prompt=prompt,
            reason=reason,
        )
