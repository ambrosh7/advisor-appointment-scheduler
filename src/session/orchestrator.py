"""
Conversation orchestrator — text in, text out.

Phases 2–6: greet → disclaimer → five intents (book, reschedule, cancel,
prepare, availability) → Google MCP side effects where configured.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from domain.calendar import MockCalendarService
from domain.clock import Clock, SystemClock
from domain.codes import BookingCodeGenerator
from domain.enums import AdvisorDisclaimerStatus, BookingStatus, Intent
from domain.formatting import format_slot_for_user
from domain.models import BookingRecord
from domain.store import BookingStore, InMemoryBookingStore
from integrations.booking_agent.cancel import (
    CancelExecutionRequest,
    CancelSideEffects,
)
from integrations.booking_agent.execute import (
    BookingExecutionRequest,
    BookingSideEffects,
)
from integrations.booking_agent.reschedule import (
    RescheduleExecutionRequest,
    RescheduleSideEffects,
)
from integrations.booking_agent.waitlist import (
    WaitlistExecutionRequest,
    WaitlistSideEffects,
)
from integrations.google_mcp.config import GoogleMcpConfig
from nlu.advice import advice_refusal_message, detect_investment_advice
from nlu.engine import NluEngine, build_default_nlu_engine
from nlu.names import extract_full_name
from nlu.pii import PII_REDIRECT_MESSAGE, detect_pii
from nlu.types import NluResult
from session import copy
from session.context import AgentTurn, SessionContext
from session.prepare import GENERIC_PREPARE, prepare_snippet
from session.states import State
from session.store import InMemorySessionStore, SessionStore

try:
    from ops.logging import bind_context, redact_for_prod
except ImportError:  # pragma: no cover
    def redact_for_prod(text: str, *, config=None) -> str:  # type: ignore[misc]
        return text

    def bind_context(**kwargs):  # type: ignore[misc]
        return kwargs

logger = logging.getLogger(__name__)

_ADVICE_REDIRECT_CAP = 3
_DECLINE = re.compile(
    r"^\s*(?:no|n|nope|cancel\s+that|never\s*mind|keep\s+it|don'?t\s+cancel)\s*[.!?]?\s*$",
    re.I,
)


class Orchestrator:
    def __init__(
        self,
        session_store: Optional[SessionStore] = None,
        calendar: Optional[MockCalendarService] = None,
        nlu: Optional[NluEngine] = None,
        clock: Optional[Clock] = None,
        *,
        booking_store: Optional[BookingStore] = None,
        booking_side_effects: Optional[BookingSideEffects] = None,
        waitlist_side_effects: Optional[WaitlistSideEffects] = None,
        cancel_side_effects: Optional[CancelSideEffects] = None,
        reschedule_side_effects: Optional[RescheduleSideEffects] = None,
        google_config: Optional[GoogleMcpConfig] = None,
        auto_greet: bool = True,
    ) -> None:
        # Use `is not None` — InMemoryBookingStore defines __len__ and is falsy when empty.
        self._store = session_store if session_store is not None else InMemorySessionStore()
        self._calendar = calendar if calendar is not None else MockCalendarService()
        self._clock = clock if clock is not None else SystemClock()
        self._nlu = (
            nlu
            if nlu is not None
            else build_default_nlu_engine(clock=self._clock, use_llm=False)
        )
        self._booking_store = (
            booking_store if booking_store is not None else InMemoryBookingStore()
        )
        self._code_gen = BookingCodeGenerator(self._booking_store)
        self._side_effects = booking_side_effects
        self._waitlist_side_effects = waitlist_side_effects
        self._cancel_side_effects = cancel_side_effects
        self._reschedule_side_effects = reschedule_side_effects
        self._google_config = (
            google_config if google_config is not None else GoogleMcpConfig.from_env()
        )
        self._auto_greet = auto_greet
        self._advice_refusal = advice_refusal_message(
            self._google_config.advice_educational_url
        )

    @property
    def store(self) -> SessionStore:
        return self._store

    @property
    def booking_store(self) -> BookingStore:
        return self._booking_store

    def create_session(self) -> AgentTurn:
        """Create a session and return the opening assistant turn (greet + disclaimer)."""
        session = SessionContext()
        messages: List[str] = []
        if self._auto_greet:
            messages.extend([copy.GREET, copy.DISCLAIMER])
            session.state = State.DISCLAIMER_AWAIT_ACK
            session.last_assistant_question = copy.DISCLAIMER
        self._store.put(session)
        return AgentTurn(
            messages=messages,
            state=session.state,
            session_id=session.session_id,
        )

    def handle(self, user_text: str, session: SessionContext) -> AgentTurn:
        messages: List[str] = []
        session.turn_count += 1
        session.touch()
        log_extra = bind_context(
            correlation_id=session.correlation_id,
            session_id=session.session_id,
            state=session.state.value,
            event="turn",
        )
        logger.info(
            "turn_in user_text=%s",
            redact_for_prod(user_text),
            extra=log_extra,
        )

        # 1) PII gate — do not advance state
        if detect_pii(user_text):
            messages.append(PII_REDIRECT_MESSAGE)
            self._store.put(session)
            return AgentTurn(messages=messages, state=session.state, session_id=session.session_id)

        # 2) Advice gate — stay in current state (cap redirects)
        if detect_investment_advice(user_text):
            session.advice_redirect_count += 1
            messages.append(self._advice_refusal)
            if session.advice_redirect_count >= _ADVICE_REDIRECT_CAP:
                messages.append(copy.ASK_INTENT)
                if session.disclaimer is AdvisorDisclaimerStatus.ACKNOWLEDGED:
                    session.state = State.INTENT_ROUTING
            self._store.put(session)
            return AgentTurn(messages=messages, state=session.state, session_id=session.session_id)

        # 3) NLU (same transcript contract for keyboard or future STT)
        nlu = self._nlu.parse(user_text, session.state.value, session)

        # 3b) Clarification gate — do not advance when policy asks a targeted question
        if nlu.needs_clarification and nlu.clarification_prompt:
            if not self._clarification_bypass(session, nlu):
                self._emit(messages, nlu.clarification_prompt, session)
                self._store.put(session)
                return AgentTurn(
                    messages=messages, state=session.state, session_id=session.session_id
                )

        # 4–5) State handler + emit texts
        self._transition(session, nlu, messages)

        # 6) Persist
        self._store.put(session)
        logger.info(
            "turn_out state=%s messages=%s",
            session.state.value,
            len(messages),
            extra=bind_context(
                correlation_id=session.correlation_id,
                session_id=session.session_id,
                state=session.state.value,
                event="turn_out",
            ),
        )
        return AgentTurn(messages=messages, state=session.state, session_id=session.session_id)

    @staticmethod
    def _clarification_bypass(session: SessionContext, nlu: NluResult) -> bool:
        if nlu.acknowledged_disclaimer or nlu.slot_choice:
            return True
        if nlu.booking_code_guess:
            return True
        if nlu.confirmed and session.state in (
            State.BOOK_CONFIRM,
            State.CANCEL_CONFIRM,
            State.RESCHEDULE_OFFER_SLOTS,
        ):
            return True
        if nlu.topic and session.state is State.PREPARE_TOPIC_OR_GENERIC:
            return True
        if (nlu.preferred_date_ist or nlu.time_window) and session.state in (
            State.AVAILABILITY_QUERY,
            State.RESCHEDULE_COLLECT_CODE,
        ):
            return True
        return False

    def _emit(self, messages: List[str], text: str, session: SessionContext) -> None:
        messages.append(text)
        session.last_assistant_question = text

    def _transition(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        state = session.state

        if state is State.GREET:
            self._emit(messages, copy.GREET, session)
            self._emit(messages, copy.DISCLAIMER, session)
            session.state = State.DISCLAIMER_AWAIT_ACK
            return

        if state is State.DISCLAIMER_AWAIT_ACK:
            if nlu.acknowledged_disclaimer or nlu.confirmed:
                session.disclaimer = AdvisorDisclaimerStatus.ACKNOWLEDGED
                session.state = State.COLLECT_NAME
                self._emit(messages, copy.ASK_NAME, session)
            else:
                self._emit(
                    messages,
                    'Please acknowledge the disclaimer with “yes” or “I understand” to continue.',
                    session,
                )
            return

        if state is State.COLLECT_NAME:
            name = extract_full_name(nlu.raw_text or "")
            if name:
                session.customer_name = name
                session.state = State.INTENT_ROUTING
                self._emit(
                    messages,
                    f"Thanks, {name.split()[0]}. {copy.ASK_INTENT}",
                    session,
                )
            else:
                self._emit(
                    messages,
                    "Please share your full name — first and last name — "
                    "for example, “Priya Sharma”.",
                    session,
                )
            return

        if state is State.INTENT_ROUTING:
            self._route_intent(session, nlu, messages)
            return

        if state is State.BOOK_TOPIC:
            if nlu.topic is not None:
                session.preference.topic = nlu.topic
                session.state = State.BOOK_TIME_PREFERENCE
                self._emit(messages, copy.ASK_TIME, session)
            else:
                self._emit(messages, copy.ASK_TOPIC, session)
            return

        if state is State.BOOK_TIME_PREFERENCE:
            if nlu.preferred_date_ist is not None:
                session.preference.preferred_date_ist = nlu.preferred_date_ist
            if nlu.time_window is not None:
                session.preference.preferred_time_window = nlu.time_window
            session.preference.raw_user_phrase = nlu.raw_text or session.preference.raw_user_phrase

            has_signal = (
                session.preference.preferred_date_ist is not None
                or session.preference.preferred_time_window is not None
            )
            if not has_signal:
                self._emit(messages, copy.ASK_TIME, session)
                return

            self._offer_slots(session, messages)
            return

        if state is State.BOOK_OFFER_SLOTS:
            if nlu.slot_choice in (1, 2):
                idx = nlu.slot_choice - 1
                if idx < len(session.offered_slots) and session.preference.topic:
                    session.selected_slot = session.offered_slots[idx]
                    session.state = State.BOOK_CONFIRM
                    self._emit(
                        messages,
                        copy.confirm_prompt(
                            session.preference.topic,
                            session.selected_slot,
                            customer_name=session.customer_name,
                        ),
                        session,
                    )
                    return
            if nlu.preferred_date_ist or nlu.time_window:
                if nlu.preferred_date_ist:
                    session.preference.preferred_date_ist = nlu.preferred_date_ist
                if nlu.time_window:
                    session.preference.preferred_time_window = nlu.time_window
                self._offer_slots(session, messages)
                return
            self._emit(
                messages,
                'Please choose a slot with “first”/“1” or “second”/“2”.',
                session,
            )
            return

        if state is State.BOOK_CONFIRM:
            if nlu.slot_choice in (1, 2) and session.offered_slots:
                idx = nlu.slot_choice - 1
                if idx < len(session.offered_slots) and session.preference.topic:
                    session.selected_slot = session.offered_slots[idx]
                    self._emit(
                        messages,
                        copy.confirm_prompt(
                            session.preference.topic,
                            session.selected_slot,
                            customer_name=session.customer_name,
                        ),
                        session,
                    )
                    return
            if nlu.confirmed and session.selected_slot and session.preference.topic:
                session.state = State.BOOK_EXECUTE_MCP
                self._execute_mcp(session, messages)
                return
            if session.selected_slot and session.preference.topic:
                self._emit(
                    messages,
                    copy.confirm_prompt(
                        session.preference.topic,
                        session.selected_slot,
                        customer_name=session.customer_name,
                    ),
                    session,
                )
            return

        if state is State.BOOK_EXECUTE_MCP:
            if nlu.confirmed and session.selected_slot and session.preference.topic:
                self._execute_mcp(session, messages)
            else:
                self._emit(messages, copy.MCP_FAILURE, session)
                session.state = State.BOOK_CONFIRM
            return

        if state is State.BOOK_WAITLIST:
            self._execute_waitlist(session, messages)
            return

        if state is State.RESCHEDULE_COLLECT_CODE:
            self._handle_reschedule_collect(session, nlu, messages)
            return

        if state is State.RESCHEDULE_OFFER_SLOTS:
            self._handle_reschedule_offer(session, nlu, messages)
            return

        if state is State.CANCEL_COLLECT_CODE:
            self._handle_cancel_collect(session, nlu, messages)
            return

        if state is State.CANCEL_CONFIRM:
            self._handle_cancel_confirm(session, nlu, messages)
            return

        if state is State.PREPARE_TOPIC_OR_GENERIC:
            self._handle_prepare(session, nlu, messages)
            return

        if state is State.AVAILABILITY_QUERY:
            self._handle_availability(session, nlu, messages)
            return

        if state is State.CLOSE:
            self._emit(messages, "This session is closed. Start a new session to book again.", session)
            return

        if state is State.ERROR_RECOVER:
            self._emit(messages, "Something went wrong. Let’s continue — say “book new”.", session)
            session.state = State.INTENT_ROUTING
            return

        self._emit(messages, copy.ASK_INTENT, session)
        session.state = State.INTENT_ROUTING

    def _execute_mcp(self, session: SessionContext, messages: List[str]) -> None:
        assert session.selected_slot is not None
        assert session.preference.topic is not None

        if self._side_effects is None:
            self._emit(
                messages,
                "Booking side effects are not configured. Set GEMINI_API_KEY and Google credentials.",
                session,
            )
            session.state = State.BOOK_CONFIRM
            session.last_mcp_error = "side_effects_not_configured"
            return

        if not session.pending_booking_code:
            session.pending_booking_code = self._code_gen.generate()

        code = session.pending_booking_code
        req = BookingExecutionRequest(
            topic=session.preference.topic,
            slot=session.selected_slot,
            booking_code=code,
            correlation_id=session.correlation_id,
            calendar_id=self._google_config.calendar_id,
            doc_id=self._google_config.docs_prebooking_id,
            advisor_email=self._google_config.gmail_advisor_to,
            customer_name=session.customer_name,
        )

        result = self._side_effects.execute(req)
        session.mcp_tool_trace = list(result.tool_trace)
        session.calendar_event_id = result.calendar_event_id
        session.gmail_draft_id = result.gmail_draft_id

        if not result.ok:
            session.last_mcp_error = (result.error or "mcp_failed")[:200]
            session.state = State.BOOK_CONFIRM
            if getattr(result, "degraded", False):
                if getattr(result, "degraded_gmail_ok", False):
                    self._emit(messages, copy.MCP_DEGRADED_RETRY, session)
                else:
                    self._emit(messages, copy.MCP_DEGRADED_RETRY_NO_EMAIL, session)
            else:
                self._emit(messages, copy.MCP_FAILURE, session)
                if result.error:
                    self._emit(messages, f"Details: {result.error}", session)
            logger.warning(
                "mcp_booking_failed degraded=%s gmail_ok=%s err=%s",
                getattr(result, "degraded", False),
                getattr(result, "degraded_gmail_ok", False),
                (result.error or "")[:120],
                extra=bind_context(
                    correlation_id=session.correlation_id,
                    session_id=session.session_id,
                    event="mcp_booking_failed",
                ),
            )
            return

        record = BookingRecord(
            code=code,
            topic=session.preference.topic,
            slot=session.selected_slot,
            created_at_utc=datetime.now(timezone.utc),
            status=BookingStatus.TENTATIVE,
            calendar_event_id=result.calendar_event_id,
            customer_name=session.customer_name,
        )
        self._booking_store.save(record)
        self._calendar.mark_busy(session.selected_slot.start_utc)

        slot_label = format_slot_for_user(session.selected_slot)
        self._emit(
            messages,
            copy.booking_success(
                code=code,
                topic=session.preference.topic.value,
                slot_label=slot_label,
                customer_name=session.customer_name,
                secure_url=result.secure_url
                or self._google_config.secure_link_for(code),
            ),
            session,
        )
        session.state = State.CLOSE
        session.last_mcp_error = None

    def _execute_waitlist(self, session: SessionContext, messages: List[str]) -> None:
        assert session.preference.topic is not None

        if not session.pending_booking_code:
            session.pending_booking_code = self._code_gen.generate()
        code = session.pending_booking_code

        hold = self._calendar.hold_waitlist_slot(session.preference, code)
        if hold is None:
            session.state = State.BOOK_TIME_PREFERENCE
            self._emit(
                messages,
                "I couldn’t create a waitlist hold. Please try another day or window.",
                session,
            )
            return

        session.selected_slot = hold
        secure_url = self._google_config.secure_link_for(code)
        slot_label = format_slot_for_user(hold)

        record = BookingRecord(
            code=code,
            topic=session.preference.topic,
            slot=hold,
            created_at_utc=datetime.now(timezone.utc),
            status=BookingStatus.WAITLISTED,
        )
        self._booking_store.save(record)

        email_ok = False
        if self._waitlist_side_effects is None:
            self._emit(messages, copy.NO_SLOTS, session)
            self._emit(
                messages,
                copy.waitlist_success(
                    code=code,
                    topic=session.preference.topic.value,
                    slot_label=slot_label,
                    secure_url=secure_url,
                    email_ok=False,
                ),
                session,
            )
            self._emit(messages, copy.WAITLIST_EMAIL_NOT_CONFIGURED, session)
            session.state = State.CLOSE
            session.last_mcp_error = "waitlist_side_effects_not_configured"
            return

        req = WaitlistExecutionRequest(
            topic=session.preference.topic,
            slot=hold,
            booking_code=code,
            correlation_id=session.correlation_id,
            advisor_email=self._google_config.gmail_advisor_to,
            secure_url=secure_url,
        )
        result = self._waitlist_side_effects.execute(req)
        session.mcp_tool_trace = list(result.tool_trace)
        session.gmail_draft_id = result.gmail_draft_id
        email_ok = result.ok
        if not result.ok:
            session.last_mcp_error = (result.error or "waitlist_email_failed")[:200]

        self._emit(messages, copy.NO_SLOTS, session)
        self._emit(
            messages,
            copy.waitlist_success(
                code=code,
                topic=session.preference.topic.value,
                slot_label=slot_label,
                secure_url=result.secure_url or secure_url,
                email_ok=email_ok,
            ),
            session,
        )
        if not email_ok:
            self._emit(messages, copy.WAITLIST_EMAIL_FAILED, session)
            if result.error:
                self._emit(messages, f"Details: {result.error}", session)
        else:
            session.last_mcp_error = None
        session.state = State.CLOSE

    def _route_intent(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        intent = nlu.intent
        if intent is Intent.BOOK_NEW or (intent is Intent.UNKNOWN and nlu.topic is not None):
            session.intent = Intent.BOOK_NEW
            if nlu.topic is not None:
                session.preference.topic = nlu.topic
                session.state = State.BOOK_TIME_PREFERENCE
                self._emit(messages, copy.ASK_TIME, session)
            else:
                session.state = State.BOOK_TOPIC
                self._emit(messages, copy.ASK_TOPIC, session)
            return

        if intent is Intent.RESCHEDULE:
            session.intent = intent
            session.state = State.RESCHEDULE_COLLECT_CODE
            self._handle_reschedule_collect(session, nlu, messages)
            return

        if intent is Intent.CANCEL:
            session.intent = intent
            session.state = State.CANCEL_COLLECT_CODE
            self._handle_cancel_collect(session, nlu, messages)
            return

        if intent is Intent.WHAT_TO_PREPARE:
            session.intent = intent
            session.state = State.PREPARE_TOPIC_OR_GENERIC
            self._handle_prepare(session, nlu, messages)
            return

        if intent is Intent.CHECK_AVAILABILITY:
            session.intent = intent
            session.state = State.AVAILABILITY_QUERY
            self._handle_availability(session, nlu, messages)
            return

        self._emit(messages, copy.ASK_INTENT, session)

    def _lookup_active_booking(self, code: str):
        record = self._booking_store.get_by_code(code)
        if record is None:
            return None, "not_found"
        if record.status is BookingStatus.CANCELLED:
            return record, "cancelled"
        if record.status is BookingStatus.WAITLISTED:
            return record, "waitlisted"
        return record, "ok"

    def _handle_reschedule_collect(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        code = nlu.booking_code_guess or session.pending_booking_code
        if not code:
            self._emit(messages, copy.ASK_BOOKING_CODE, session)
            return

        record, status = self._lookup_active_booking(code)
        if status == "not_found":
            session.pending_booking_code = None
            self._emit(messages, copy.CODE_NOT_FOUND, session)
            return
        if status != "ok" or record is None:
            session.pending_booking_code = None
            self._emit(messages, copy.CODE_NOT_ACTIVE, session)
            return

        session.pending_booking_code = code
        session.calendar_event_id = record.calendar_event_id
        session.preference.topic = record.topic

        if nlu.preferred_date_ist is not None:
            session.preference.preferred_date_ist = nlu.preferred_date_ist
        if nlu.time_window is not None:
            session.preference.preferred_time_window = nlu.time_window

        has_signal = (
            session.preference.preferred_date_ist is not None
            or session.preference.preferred_time_window is not None
        )
        if not has_signal:
            self._emit(messages, copy.ASK_RESCHEDULE_TIME, session)
            return

        self._offer_reschedule_slots(session, messages, old_slot_start=record.slot.start_utc)

    def _offer_reschedule_slots(
        self,
        session: SessionContext,
        messages: List[str],
        *,
        old_slot_start,
    ) -> None:
        # Free the old mock slot so it can appear again if still matching
        self._calendar.mark_free(old_slot_start)
        slots = self._calendar.find_two_slots(session.preference, self._clock)
        session.offered_slots = slots
        session.selected_slot = None
        if not slots:
            self._calendar.mark_busy(old_slot_start)
            self._emit(messages, copy.AVAILABILITY_NONE, session)
            session.state = State.RESCHEDULE_COLLECT_CODE
            session.preference.preferred_date_ist = None
            session.preference.preferred_time_window = None
            return
        session.state = State.RESCHEDULE_OFFER_SLOTS
        self._emit(messages, copy.offer_slots_message(slots), session)

    def _handle_reschedule_offer(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        if nlu.slot_choice in (1, 2):
            idx = nlu.slot_choice - 1
            if idx < len(session.offered_slots) and session.preference.topic:
                session.selected_slot = session.offered_slots[idx]
                assert session.pending_booking_code
                self._emit(
                    messages,
                    copy.reschedule_confirm_prompt(
                        session.preference.topic,
                        session.selected_slot,
                        session.pending_booking_code,
                    ),
                    session,
                )
                return

        if nlu.preferred_date_ist or nlu.time_window:
            if nlu.preferred_date_ist:
                session.preference.preferred_date_ist = nlu.preferred_date_ist
            if nlu.time_window:
                session.preference.preferred_time_window = nlu.time_window
            code = session.pending_booking_code
            record = self._booking_store.get_by_code(code) if code else None
            old_start = record.slot.start_utc if record else None
            if old_start is not None:
                self._offer_reschedule_slots(session, messages, old_slot_start=old_start)
            return

        if nlu.confirmed and session.selected_slot and session.pending_booking_code:
            self._execute_reschedule(session, messages)
            return

        if session.selected_slot and session.preference.topic and session.pending_booking_code:
            self._emit(
                messages,
                copy.reschedule_confirm_prompt(
                    session.preference.topic,
                    session.selected_slot,
                    session.pending_booking_code,
                ),
                session,
            )
            return

        self._emit(
            messages,
            'Please choose a slot with “first”/“1” or “second”/“2”.',
            session,
        )

    def _execute_reschedule(self, session: SessionContext, messages: List[str]) -> None:
        assert session.selected_slot is not None
        assert session.pending_booking_code is not None
        assert session.preference.topic is not None

        code = session.pending_booking_code
        record = self._booking_store.get_by_code(code)
        if record is None or record.status is not BookingStatus.TENTATIVE:
            self._emit(messages, copy.CODE_NOT_ACTIVE, session)
            session.state = State.INTENT_ROUTING
            return

        old_slot = record.slot
        new_slot = session.selected_slot
        new_event_id = record.calendar_event_id

        if self._reschedule_side_effects is not None:
            req = RescheduleExecutionRequest(
                topic=session.preference.topic,
                old_slot=old_slot,
                new_slot=new_slot,
                booking_code=code,
                old_calendar_event_id=record.calendar_event_id,
                correlation_id=session.correlation_id,
                calendar_id=self._google_config.calendar_id,
                doc_id=self._google_config.docs_prebooking_id,
            )
            result = self._reschedule_side_effects.execute(req)
            session.mcp_tool_trace = list(result.tool_trace)
            if not result.ok:
                session.last_mcp_error = (result.error or "reschedule_failed")[:200]
                self._emit(messages, copy.MCP_FAILURE, session)
                if result.error:
                    self._emit(messages, f"Details: {result.error}", session)
                return
            new_event_id = result.calendar_event_id
            session.calendar_event_id = new_event_id
            session.last_mcp_error = None
        else:
            session.mcp_tool_trace = []

        self._calendar.mark_free(old_slot.start_utc)
        self._calendar.mark_busy(new_slot.start_utc)
        record.slot = new_slot
        record.calendar_event_id = new_event_id
        record.status = BookingStatus.TENTATIVE
        self._booking_store.save(record)

        slot_label = format_slot_for_user(new_slot)
        self._emit(
            messages,
            copy.reschedule_success(
                code=code,
                topic=session.preference.topic.value,
                slot_label=slot_label,
                secure_url=self._google_config.secure_link_for(code),
            ),
            session,
        )
        session.state = State.CLOSE

    def _handle_cancel_collect(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        code = nlu.booking_code_guess or session.pending_booking_code
        if not code:
            self._emit(messages, copy.ASK_BOOKING_CODE, session)
            return

        record, status = self._lookup_active_booking(code)
        if status == "not_found":
            session.pending_booking_code = None
            self._emit(messages, copy.CODE_NOT_FOUND, session)
            return
        if status != "ok" or record is None:
            session.pending_booking_code = None
            self._emit(messages, copy.CODE_NOT_ACTIVE, session)
            return

        session.pending_booking_code = code
        session.calendar_event_id = record.calendar_event_id
        session.preference.topic = record.topic
        session.selected_slot = record.slot
        session.state = State.CANCEL_CONFIRM
        self._emit(
            messages,
            (
                f"Found booking {code} for {record.topic.value} at "
                f"{format_slot_for_user(record.slot)}.\n"
                f"{copy.ASK_CANCEL_CONFIRM}"
            ),
            session,
        )

    def _handle_cancel_confirm(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        if _DECLINE.match((nlu.raw_text or "").strip()):
            self._emit(messages, copy.CANCEL_ABORTED, session)
            session.state = State.INTENT_ROUTING
            self._emit(messages, copy.ASK_INTENT, session)
            return

        if not nlu.confirmed:
            self._emit(messages, copy.ASK_CANCEL_CONFIRM, session)
            return

        self._execute_cancel(session, messages)

    def _execute_cancel(self, session: SessionContext, messages: List[str]) -> None:
        code = session.pending_booking_code
        if not code:
            self._emit(messages, copy.ASK_BOOKING_CODE, session)
            session.state = State.CANCEL_COLLECT_CODE
            return

        record = self._booking_store.get_by_code(code)
        if record is None or record.status is not BookingStatus.TENTATIVE:
            self._emit(messages, copy.CODE_NOT_ACTIVE, session)
            session.state = State.INTENT_ROUTING
            return

        if self._cancel_side_effects is not None:
            req = CancelExecutionRequest(
                topic=record.topic,
                slot=record.slot,
                booking_code=code,
                calendar_event_id=record.calendar_event_id,
                correlation_id=session.correlation_id,
                calendar_id=self._google_config.calendar_id,
                doc_id=self._google_config.docs_prebooking_id,
                advisor_email=self._google_config.gmail_advisor_to,
            )
            result = self._cancel_side_effects.execute(req)
            session.mcp_tool_trace = list(result.tool_trace)
            session.gmail_draft_id = result.gmail_draft_id
            if not result.ok:
                session.last_mcp_error = (result.error or "cancel_failed")[:200]
                self._emit(messages, copy.MCP_FAILURE, session)
                if result.error:
                    self._emit(messages, f"Details: {result.error}", session)
                return
            session.last_mcp_error = None
        else:
            session.mcp_tool_trace = []

        self._calendar.mark_free(record.slot.start_utc)
        self._booking_store.update_status(code, BookingStatus.CANCELLED)
        record = self._booking_store.get_by_code(code)
        assert record is not None
        record.calendar_event_id = None
        self._booking_store.save(record)

        self._emit(
            messages,
            copy.cancel_summary(
                code=code,
                topic=record.topic.value,
                slot_label=format_slot_for_user(record.slot),
            ),
            session,
        )
        session.state = State.CLOSE

    def _handle_prepare(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        topic = nlu.topic or session.preference.topic
        if topic is None:
            self._emit(messages, GENERIC_PREPARE, session)
            return

        session.preference.topic = topic
        self._emit(messages, prepare_snippet(topic), session)
        session.state = State.INTENT_ROUTING
        self._emit(messages, copy.ASK_INTENT, session)

    def _handle_availability(
        self,
        session: SessionContext,
        nlu: NluResult,
        messages: List[str],
    ) -> None:
        if nlu.preferred_date_ist is not None:
            session.preference.preferred_date_ist = nlu.preferred_date_ist
        if nlu.time_window is not None:
            session.preference.preferred_time_window = nlu.time_window
        if nlu.topic is not None:
            session.preference.topic = nlu.topic

        has_signal = (
            session.preference.preferred_date_ist is not None
            or session.preference.preferred_time_window is not None
        )
        if not has_signal:
            self._emit(messages, copy.ASK_TIME, session)
            return

        slots = self._calendar.peek_two_slots(session.preference, self._clock)
        session.offered_slots = slots
        session.selected_slot = None
        if not slots:
            self._emit(messages, copy.AVAILABILITY_NONE, session)
        else:
            self._emit(messages, copy.availability_offer(slots), session)
        session.state = State.INTENT_ROUTING

    def _offer_slots(self, session: SessionContext, messages: List[str]) -> None:
        if session.preference.topic is None:
            session.state = State.BOOK_TOPIC
            self._emit(messages, copy.ASK_TOPIC, session)
            return

        slots = self._calendar.find_two_slots(session.preference, self._clock)
        session.offered_slots = slots
        session.selected_slot = None

        if not slots:
            session.state = State.BOOK_WAITLIST
            self._execute_waitlist(session, messages)
            return

        session.state = State.BOOK_OFFER_SLOTS
        self._emit(messages, copy.offer_slots_message(slots), session)
