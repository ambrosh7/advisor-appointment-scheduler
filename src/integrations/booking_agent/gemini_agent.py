"""
Gemini LLM agent that tool-calls Google MCP tools for booking side effects.

Uses the modern ``google.genai`` SDK (``google.generativeai`` is deprecated and
mis-routes model IDs).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

from integrations.booking_agent.execute import (
    BookingExecutionRequest,
    BookingExecutionResult,
    advisor_email_body,
    format_prebooking_line,
)
from integrations.google_mcp.config import GoogleMcpConfig

logger = logging.getLogger(__name__)


class ToolDispatcher(Protocol):
    def dispatch(self, name: str, arguments: dict) -> Any: ...

    def calendar_delete_hold(self, event_id: str, calendar_id: str) -> None: ...


SYSTEM_INSTRUCTION = """You are the booking side-effects agent for Advisor Appointment Scheduler.
You MUST call the provided tools to perform real side effects.
Do not claim success without tool results. Never invent event_id or message ids.
Never collect or write PII (phone, email of the caller, account numbers).
Call tools in this order:
1) calendar_create_hold   (local Google Calendar)
2) docs_append_prebooking (remote Railway Docs MCP)
3) gmail_create_draft     (remote Railway Gmail MCP — sends a real email)
If docs_append_prebooking fails after a calendar hold was created, call calendar_delete_hold
to compensate, then stop.
After all three succeed, reply with a short JSON object:
{"status":"ok","calendar_event_id":"...","gmail_message_id":"..."}
"""

TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "name": "calendar_create_hold",
        "description": (
            "Create a tentative Google Calendar hold. "
            "Title must be: Advisor Q&A — {Topic} — {Code}"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_utc": {"type": "string", "description": "ISO-8601 UTC start"},
                "end_utc": {"type": "string", "description": "ISO-8601 UTC end"},
                "calendar_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "title",
                "start_utc",
                "end_utc",
                "calendar_id",
                "idempotency_key",
            ],
        },
    },
    {
        "name": "calendar_delete_hold",
        "description": "Delete a tentative Google Calendar hold (compensation).",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "calendar_id": {"type": "string"},
            },
            "required": ["event_id", "calendar_id"],
        },
    },
    {
        "name": "docs_append_prebooking",
        "description": "Append a line to the Advisor Pre-Bookings Google Doc. No PII.",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "line": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["doc_id", "line", "idempotency_key"],
        },
    },
    {
        "name": "gmail_create_draft",
        "description": (
            "Notify the advisor by email via Railway MCP gmail_send_email. "
            "NOTE: this SENDS a real email (not a draft) in the current hybrid setup."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body_markdown": {"type": "string"},
            },
            "required": ["to", "subject", "body_markdown"],
        },
    },
]

GenerateContentFn = Callable[..., Any]


class GeminiBookingAgent:
    """LLM agent: Gemini function-calling → Google MCP / hybrid tools."""

    def __init__(
        self,
        tools: ToolDispatcher,
        config: Optional[GoogleMcpConfig] = None,
        *,
        generate_content: Optional[GenerateContentFn] = None,
        max_turns: int = 8,
    ) -> None:
        self._tools = tools
        self._config = config or GoogleMcpConfig.from_env()
        self._generate_content = generate_content
        self._max_turns = max_turns
        self._genai_client: Any = None

    def execute(self, request: BookingExecutionRequest) -> BookingExecutionResult:
        secure_url = self._config.secure_link_for(request.booking_code)
        trace: List[str] = []
        calendar_event_id: Optional[str] = None
        gmail_draft_id: Optional[str] = None

        if not self._config.gemini_api_key and self._generate_content is None:
            return BookingExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                secure_url=secure_url,
                error="GEMINI_API_KEY is not configured",
                tool_trace=trace,
            )

        user_prompt = self._build_user_prompt(request, secure_url)

        try:
            chat = self._start_chat()
            response = chat.send_message(user_prompt)

            for _ in range(self._max_turns):
                fn_calls = _extract_function_calls(response)
                if not fn_calls:
                    break

                parts_out: List[Any] = []
                for call in fn_calls:
                    name = call["name"]
                    args = call.get("args") or {}
                    trace.append(name)
                    logger.info(
                        "gemini_tool_call name=%s correlation_id=%s",
                        name,
                        request.correlation_id,
                    )
                    try:
                        result = self._tools.dispatch(name, dict(args))
                        if name == "calendar_create_hold":
                            calendar_event_id = str(result)
                        if name == "gmail_create_draft":
                            gmail_draft_id = str(result)
                        parts_out.append(
                            _function_response_part(name, {"result": result})
                        )
                    except Exception as exc:  # noqa: BLE001
                        parts_out.append(
                            _function_response_part(
                                name, {"error": f"{type(exc).__name__}: {exc}"}
                            )
                        )
                        if calendar_event_id and name in {
                            "docs_append_prebooking",
                            "gmail_create_draft",
                        }:
                            try:
                                self._tools.calendar_delete_hold(
                                    event_id=calendar_event_id,
                                    calendar_id=request.calendar_id
                                    or self._config.calendar_id,
                                )
                                trace.append("calendar_delete_hold")
                                calendar_event_id = None
                            except Exception:  # noqa: BLE001
                                logger.exception("compensation delete failed")
                        return BookingExecutionResult(
                            ok=False,
                            booking_code=request.booking_code,
                            secure_url=secure_url,
                            calendar_event_id=calendar_event_id,
                            gmail_draft_id=gmail_draft_id,
                            tool_trace=trace,
                            error=f"MCP tool {name} failed: {exc}",
                        )

                response = chat.send_message(parts_out)

            required = {
                "calendar_create_hold",
                "docs_append_prebooking",
                "gmail_create_draft",
            }
            missing = required - set(trace)
            if missing:
                return BookingExecutionResult(
                    ok=False,
                    booking_code=request.booking_code,
                    secure_url=secure_url,
                    calendar_event_id=calendar_event_id,
                    gmail_draft_id=gmail_draft_id,
                    tool_trace=trace,
                    error=f"Gemini did not call required MCP tools: {sorted(missing)}",
                )

            return BookingExecutionResult(
                ok=True,
                booking_code=request.booking_code,
                secure_url=secure_url,
                calendar_event_id=calendar_event_id,
                gmail_draft_id=gmail_draft_id,
                tool_trace=trace,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gemini booking agent failed")
            return BookingExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                secure_url=secure_url,
                calendar_event_id=calendar_event_id,
                gmail_draft_id=gmail_draft_id,
                tool_trace=trace,
                error=str(exc),
            )

    def _build_user_prompt(
        self, request: BookingExecutionRequest, secure_url: str
    ) -> str:
        name_bit = f" — {request.customer_name}" if request.customer_name else ""
        title = (
            f"Advisor Q&A — {request.topic.value} — {request.booking_code}{name_bit}"
        )
        line = format_prebooking_line(
            code=request.booking_code,
            topic=request.topic,
            slot=request.slot,
            customer_name=request.customer_name,
        )
        body = advisor_email_body(
            code=request.booking_code,
            topic=request.topic,
            slot=request.slot,
            secure_url=secure_url,
            customer_name=request.customer_name,
        )
        cal_id = request.calendar_id or self._config.calendar_id
        doc_id = request.doc_id or self._config.docs_prebooking_id
        to_addr = request.advisor_email or self._config.gmail_advisor_to
        idem = f"booking:{request.booking_code}"
        subject = (
            f"Advisor pre-booking {request.booking_code} — "
            f"{request.topic.value}{name_bit}"
        )

        return (
            "Execute the booking side effects using MCP tools.\n"
            f"booking_code: {request.booking_code}\n"
            f"customer_name: {request.customer_name or '(none)'}\n"
            f"correlation_id: {request.correlation_id}\n"
            f"calendar_title: {title}\n"
            f"start_utc: {request.slot.start_utc.isoformat()}\n"
            f"end_utc: {request.slot.end_utc.isoformat()}\n"
            f"calendar_id: {cal_id}\n"
            f"idempotency_key: {idem}\n"
            f"doc_id: {doc_id}\n"
            f"docs_line: {line}\n"
            f"gmail_to: {to_addr}\n"
            f"gmail_subject: {subject}\n"
            f"gmail_body_markdown:\n{body}\n"
            "Call the three tools now with these values."
        )

    def _start_chat(self) -> Any:
        if self._generate_content is not None:
            return _InjectableChat(self._generate_content)

        from google import genai
        from google.genai import types

        # Keep Client alive for the whole execute() turn — chats hold a weak
        # reference and GC would close the httpx session mid-flight.
        if self._genai_client is None:
            self._genai_client = genai.Client(api_key=self._config.gemini_api_key)
        client = self._genai_client
        declarations = [
            types.FunctionDeclaration(
                name=d["name"],
                description=d["description"],
                parameters=d["parameters"],
            )
            for d in TOOL_DECLARATIONS
        ]
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        return client.chats.create(model=self._config.gemini_model, config=config)


class _InjectableChat:
    """Test double: scripted generate_content sequence via chat.send_message."""

    def __init__(self, generate_content: GenerateContentFn) -> None:
        self._generate_content = generate_content
        self._turn = 0
        self._history: List[Any] = []

    def send_message(self, content: Any) -> Any:
        self._history.append(content)
        response = self._generate_content(self._turn, content, list(self._history))
        self._turn += 1
        return response


def _extract_function_calls(response: Any) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    # google.genai: response.function_calls
    try:
        fcs = getattr(response, "function_calls", None) or []
        for fc in fcs:
            name = getattr(fc, "name", None)
            raw_args = getattr(fc, "args", None) or {}
            if name:
                calls.append({"name": name, "args": dict(raw_args)})
    except Exception:  # noqa: BLE001
        pass

    if calls:
        return calls

    # candidates/parts fallback (old + new SDKs)
    try:
        cands = getattr(response, "candidates", None) or []
        for cand in cands:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc:
                    name = getattr(fc, "name", None)
                    raw_args = getattr(fc, "args", None) or {}
                    if name:
                        calls.append({"name": name, "args": dict(raw_args)})
    except Exception:  # noqa: BLE001
        pass

    # Scripted dict responses for tests
    if not calls and isinstance(response, dict):
        for item in response.get("function_calls") or []:
            calls.append({"name": item["name"], "args": item.get("args") or {}})
    return calls


def _function_response_part(name: str, payload: dict) -> Any:
    try:
        from google.genai import types

        return types.Part.from_function_response(name=name, response=payload)
    except Exception:  # noqa: BLE001
        return {"function_response": {"name": name, "response": payload}}


def scripted_gemini_success_sequence(
    request: BookingExecutionRequest,
    config: GoogleMcpConfig,
) -> GenerateContentFn:
    """Test helper: Gemini “decides” to call the three MCP tools in order."""

    title = f"Advisor Q&A — {request.topic.value} — {request.booking_code}"
    idem = f"booking:{request.booking_code}"
    cal_id = request.calendar_id or config.calendar_id
    doc_id = request.doc_id or config.docs_prebooking_id
    to_addr = request.advisor_email or config.gmail_advisor_to
    line = format_prebooking_line(
        code=request.booking_code, topic=request.topic, slot=request.slot
    )
    secure = config.secure_link_for(request.booking_code)
    body = advisor_email_body(
        code=request.booking_code,
        topic=request.topic,
        slot=request.slot,
        secure_url=secure,
    )

    planned = [
        {
            "function_calls": [
                {
                    "name": "calendar_create_hold",
                    "args": {
                        "title": title,
                        "start_utc": request.slot.start_utc.isoformat(),
                        "end_utc": request.slot.end_utc.isoformat(),
                        "calendar_id": cal_id,
                        "idempotency_key": idem,
                    },
                }
            ]
        },
        {
            "function_calls": [
                {
                    "name": "docs_append_prebooking",
                    "args": {
                        "doc_id": doc_id,
                        "line": line,
                        "idempotency_key": request.booking_code,
                    },
                }
            ]
        },
        {
            "function_calls": [
                {
                    "name": "gmail_create_draft",
                    "args": {
                        "to": to_addr,
                        "subject": (
                            f"Advisor pre-booking {request.booking_code} — "
                            f"{request.topic.value}"
                        ),
                        "body_markdown": body,
                    },
                }
            ]
        },
        {"function_calls": []},
    ]

    def _gen(turn: int, content: Any, history: Sequence[Any]) -> Any:
        _ = content, history
        if turn < len(planned):
            return planned[turn]
        return {"function_calls": []}

    return _gen
