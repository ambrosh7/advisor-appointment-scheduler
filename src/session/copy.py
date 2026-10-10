"""Assistant copy used by the orchestrator (chat + later TTS)."""

from __future__ import annotations

from domain.enums import Topic
from domain.formatting import format_slot_for_user
from domain.models import TimeSlot

GREET = (
    "Hi — I’m the Advisor Appointment Scheduler. "
    "I can help you secure a tentative slot with a human advisor."
)

DISCLAIMER = (
    "Before we continue: this chat is informational only and is not investment advice. "
    "Please reply “yes” or “I understand” to acknowledge."
)

ASK_NAME = (
    "Thanks. What’s your full name? "
    "I’ll use it to label your tentative booking — for example, “Priya Sharma”."
)

ASK_INTENT = (
    "What would you like to do? You can book a new slot, reschedule, cancel, "
    "ask what to prepare, or check availability."
)

ASK_TOPIC = (
    "Which topic is this consultation about?\n"
    "• KYC Onboarding\n"
    "• SIP Mandates\n"
    "• Statements / Tax Docs\n"
    "• Withdrawals & Timelines\n"
    "• Account Changes / Nominee\n"
    "You can say e.g. “topic kyc” or “SIP”."
)

ASK_TIME = (
    "When would you prefer to talk? Share a day and window in IST — "
    "e.g. “time monday afternoon”, “tomorrow morning”, or “2026-04-10 evening”."
)

ASK_BOOKING_CODE = (
    "Please share your booking code (format like NL-A742). "
    "We only use the code — never phone or email in this chat."
)

ASK_RESCHEDULE_TIME = (
    "Got it. When would you prefer the new slot? Share a day and window in IST — "
    "e.g. “time tuesday morning” or “tomorrow afternoon”."
)

CODE_NOT_FOUND = (
    "I couldn’t find an active booking with that code. "
    "Please check the code and try again, or say “book new” to start fresh."
)

CODE_NOT_ACTIVE = (
    "That booking isn’t active anymore (cancelled or waitlisted). "
    "Say “book new” to schedule a fresh slot."
)

ASK_CANCEL_CONFIRM = (
    "Please confirm you want to cancel this tentative booking. "
    'Reply “yes” or “confirm” to cancel, or “no” to keep it.'
)

CANCEL_SUCCESS = (
    "Your tentative booking has been cancelled. "
    "A cancellation note was recorded for the advisor."
)

CANCEL_ABORTED = "Okay — I won’t cancel. What would you like to do next?"

AVAILABILITY_NONE = (
    "I don’t see free slots for that preference right now. "
    "You can try another day/window, or say “book new” to start a booking "
    "(waitlist is available if nothing matches)."
)

AVAILABILITY_SUGGEST_BOOK = (
    "Those are peek-only — nothing was booked. "
    'Say “book new” (and the same preference) when you’re ready to reserve a slot.'
)

RESCHEDULE_SUCCESS_PREFIX = "You’re rescheduled tentatively."

NO_SLOTS = (
    "I couldn’t find matching slots for that preference. "
    "I’ll place you on the waitlist and notify an advisor."
)

MCP_DEFERRED = (
    "You’re ready to confirm — calendar hold, notes, and email draft via Google MCP "
    "will run in Phase 4. Thanks for testing the chat path."
)

MCP_FAILURE = (
    "I couldn’t complete the calendar hold / notes / email draft just now. "
    "Please try confirming again in a moment, or start a new session."
)

# Same string for chat and voice (Phase 8 runbook — degraded MCP outage).
MCP_DEGRADED_RETRY = (
    "I couldn’t complete the calendar hold just now. "
    "I’ve queued an advisor email draft with your booking details — "
    "please try confirming again in a moment."
)

MCP_DEGRADED_RETRY_NO_EMAIL = (
    "I couldn’t complete the calendar hold or queue an advisor email just now. "
    "Please try confirming again in a moment, or start a new session."
)

WAITLIST_EMAIL_NOT_CONFIGURED = (
    "You’re on the waitlist, but the advisor notification email isn’t configured yet. "
    "An advisor can still follow up using your booking code."
)

WAITLIST_EMAIL_FAILED = (
    "You’re on the waitlist. I couldn’t create the advisor email draft just now — "
    "please keep your booking code handy."
)


def booking_success(
    code: str,
    topic: str,
    slot_label: str,
    secure_url: str,
    *,
    customer_name: str = "",
) -> str:
    name_line = f"• Name: {customer_name}\n" if customer_name else ""
    return (
        f"You’re booked tentatively.\n"
        f"{name_line}"
        f"• Booking code: {code}\n"
        f"• Topic: {topic}\n"
        f"• Slot: {slot_label}\n"
        f"• Complete your contact details securely (outside this chat): {secure_url}\n"
        f"Advisor notification prepared (calendar hold + pre-booking note + email)."
    )


def waitlist_success(
    code: str,
    topic: str,
    slot_label: str,
    secure_url: str,
    *,
    email_ok: bool = True,
) -> str:
    lines = [
        "No matching slots were free — I’ve placed you on the waitlist.",
        f"• Booking code: {code}",
        f"• Topic: {topic}",
        f"• Waitlist hold (IST): {slot_label}",
        f"• Complete your contact details securely (outside this chat): {secure_url}",
    ]
    if email_ok:
        lines.append("An advisor notification draft was created via Google MCP.")
    return "\n".join(lines)

TOPICS_LIST = ", ".join(t.value for t in Topic)


def offer_slots_message(slots: list[TimeSlot]) -> str:
    lines = ["Here are two available slots (IST):"]
    for i, slot in enumerate(slots, start=1):
        lines.append(f"{i}. {format_slot_for_user(slot)}")
    lines.append('Reply “first” / “1” or “second” / “2” to choose.')
    return "\n".join(lines)


def confirm_prompt(topic: Topic, slot: TimeSlot, *, customer_name: str = "") -> str:
    name_line = f"• Name: {customer_name}\n" if customer_name else ""
    return (
        f"Please confirm this tentative booking:\n"
        f"{name_line}"
        f"• Topic: {topic.value}\n"
        f"• Slot: {format_slot_for_user(slot)}\n"
        f'Reply “yes” or “confirm” to create the calendar hold and drafts, '
        f'or pick another slot with “1”/“2”.'
    )


def reschedule_confirm_prompt(topic: Topic, slot: TimeSlot, code: str) -> str:
    return (
        f"Please confirm the new slot for booking {code}:\n"
        f"• Topic: {topic.value}\n"
        f"• New slot: {format_slot_for_user(slot)}\n"
        f'Reply “yes” or “confirm” to move the calendar hold, '
        f'or pick another slot with “1”/“2”.'
    )


def reschedule_success(
    code: str,
    topic: str,
    slot_label: str,
    secure_url: str,
) -> str:
    return (
        f"{RESCHEDULE_SUCCESS_PREFIX}\n"
        f"• Booking code: {code}\n"
        f"• Topic: {topic}\n"
        f"• New slot: {slot_label}\n"
        f"• Complete your contact details securely (outside this chat): {secure_url}\n"
        f"Calendar hold updated (old hold removed, new hold created)."
    )


def cancel_summary(code: str, topic: str, slot_label: str) -> str:
    return (
        f"{CANCEL_SUCCESS}\n"
        f"• Booking code: {code}\n"
        f"• Topic: {topic}\n"
        f"• Former slot: {slot_label}"
    )


def availability_offer(slots: list[TimeSlot]) -> str:
    lines = ["Here are available windows (IST) — peek only, nothing booked:"]
    for i, slot in enumerate(slots, start=1):
        lines.append(f"{i}. {format_slot_for_user(slot)}")
    lines.append(AVAILABILITY_SUGGEST_BOOK)
    return "\n".join(lines)
