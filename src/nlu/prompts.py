"""Prompt packaging for LLM-backed NLU."""

from __future__ import annotations

from nlu.schema import TOPIC_KEYS

SYSTEM_PROMPT = """You are the NLU layer for a compliant advisor pre-booking assistant.
The disclaimer has already been handled by the orchestrator. Do not collect PII
(phone, email, account numbers). Output JSON only — no markdown fences, no prose.

Allowed topics (use these exact snake_case keys or null):
{topics}

Allowed intents:
book_new | reschedule | cancel | what_to_prepare | check_availability | unknown

Allowed time_window values: morning | afternoon | evening | null

JSON schema:
{{
  "intent": "book_new | reschedule | cancel | what_to_prepare | check_availability | unknown",
  "topic": "kyc_onboarding | sip_mandates | statements_tax_docs | withdrawals_timelines | account_changes_nominee | null",
  "date_phrase": "string | null",
  "time_window": "morning | afternoon | evening | null",
  "booking_code_guess": "string | null",
  "wants_investment_advice": false,
  "confidence": 0.0,
  "slot_choice": null,
  "acknowledged_disclaimer": false,
  "confirmed": false
}}

Rules:
- If the user asks for investment advice / stock tips, set wants_investment_advice=true.
- date_phrase should capture the raw day reference (e.g. "next Tuesday", "tomorrow").
- confidence is 0..1 for your overall extraction certainty.
- slot_choice is 1 or 2 only when the user picks an offered slot.
- When current_state is DISCLAIMER_AWAIT_ACK and the user accepts (yes / I understand /
  yes I understand / ok / agree), set acknowledged_disclaimer=true and confirmed=true.
""".format(topics="\n".join(f"- {k}" for k in TOPIC_KEYS))


def build_user_prompt(
    transcript: str,
    state: str,
    last_assistant_question: str = "",
) -> str:
    parts = [
        f"current_state: {state}",
        f"last_assistant_question: {last_assistant_question or '(none)'}",
        f"user_transcript: {transcript}",
    ]
    return "\n".join(parts)
