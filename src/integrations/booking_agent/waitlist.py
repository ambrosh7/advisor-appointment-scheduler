"""Waitlist side effects — direct MCP gmail_create_draft (no Gemini)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from domain.enums import Topic
from domain.models import TimeSlot
from integrations.booking_agent.execute import advisor_email_body
from integrations.google_mcp.config import GoogleMcpConfig


@dataclass
class WaitlistExecutionRequest:
    topic: Topic
    slot: TimeSlot
    booking_code: str
    correlation_id: str = ""
    advisor_email: str = ""
    secure_url: str = ""


@dataclass
class WaitlistExecutionResult:
    ok: bool
    booking_code: str
    secure_url: str = ""
    gmail_draft_id: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)
    error: Optional[str] = None


class ToolDispatcher(Protocol):
    def dispatch(self, name: str, arguments: dict) -> Any: ...


class WaitlistSideEffects(Protocol):
    def execute(self, request: WaitlistExecutionRequest) -> WaitlistExecutionResult: ...


def waitlist_email_body(
    *,
    code: str,
    topic: Topic,
    slot: TimeSlot,
    secure_url: str,
) -> str:
    base = advisor_email_body(
        code=code, topic=topic, slot=slot, secure_url=secure_url
    )
    return (
        "## Waitlist hold (no matching slots)\n\n"
        + base.replace("## Tentative advisor booking\n\n", "")
    )


class ExecuteWaitlistSideEffects:
    """Invoked from BOOK_WAITLIST: create advisor Gmail draft via MCP tools."""

    def __init__(
        self,
        tools: ToolDispatcher,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._tools = tools
        self._config = config or GoogleMcpConfig.from_env()

    def execute(self, request: WaitlistExecutionRequest) -> WaitlistExecutionResult:
        secure_url = request.secure_url or self._config.secure_link_for(
            request.booking_code
        )
        to_addr = request.advisor_email or self._config.gmail_advisor_to
        if not to_addr:
            return WaitlistExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                secure_url=secure_url,
                error="GOOGLE_GMAIL_ADVISOR_TO is not configured",
            )

        subject = (
            f"Advisor waitlist {request.booking_code} — {request.topic.value}"
        )
        body = waitlist_email_body(
            code=request.booking_code,
            topic=request.topic,
            slot=request.slot,
            secure_url=secure_url,
        )
        trace: List[str] = []
        try:
            draft_id = self._tools.dispatch(
                "gmail_create_draft",
                {
                    "to": to_addr,
                    "subject": subject,
                    "body_markdown": body,
                    "idempotency_key": f"waitlist:{request.booking_code}",
                },
            )
            trace.append("gmail_create_draft")
            return WaitlistExecutionResult(
                ok=True,
                booking_code=request.booking_code,
                secure_url=secure_url,
                gmail_draft_id=str(draft_id) if draft_id is not None else None,
                tool_trace=trace,
            )
        except Exception as exc:  # noqa: BLE001
            return WaitlistExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                secure_url=secure_url,
                tool_trace=trace,
                error=f"{type(exc).__name__}: {exc}",
            )

    def __call__(self, request: WaitlistExecutionRequest) -> WaitlistExecutionResult:
        return self.execute(request)
