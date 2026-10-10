"""Wire Gemini booking agent + waitlist/cancel/reschedule: local Calendar + Railway MCP."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from integrations.booking_agent.cancel import ExecuteCancelSideEffects
from integrations.booking_agent.direct import DirectBookingSideEffects
from integrations.booking_agent.execute import ExecuteBookingSideEffects
from integrations.booking_agent.gemini_agent import GeminiBookingAgent
from integrations.booking_agent.reschedule import ExecuteRescheduleSideEffects
from integrations.booking_agent.waitlist import ExecuteWaitlistSideEffects
from integrations.google_mcp.clients import GoogleWorkspaceClients
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.remote_client import RemoteMcpClient
from integrations.google_mcp.server import set_tools
from integrations.google_mcp.tools import GoogleMcpTools
from ops.degraded import GmailOnlyDegradedQueue, ResilientBookingSideEffects

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Phase4SideEffects:
    booking: Any  # ExecuteBookingSideEffects | ResilientBookingSideEffects
    waitlist: ExecuteWaitlistSideEffects
    cancel: ExecuteCancelSideEffects
    reschedule: ExecuteRescheduleSideEffects
    tools: HybridBookingTools


def _build_hybrid_tools(
    config: GoogleMcpConfig,
    *,
    clients: Optional[GoogleWorkspaceClients] = None,
    remote: Optional[RemoteMcpClient] = None,
    correlation_id: Optional[str] = None,
) -> HybridBookingTools:
    cid = correlation_id or str(uuid.uuid4())
    if clients is None:
        clients = GoogleWorkspaceClients.from_config(config, correlation_id=cid)
    else:
        clients.correlation_id = cid

    local = GoogleMcpTools(clients, config)
    set_tools(local)

    if remote is None:
        if not config.mcp_bearer_token:
            raise RuntimeError("MCP_HTTP_BEARER_TOKEN is required for hybrid Docs/Gmail")
        remote = RemoteMcpClient(config.mcp_server_url, config.mcp_bearer_token)

    logger.info(
        "Phase 4 hybrid tools: calendar=local docs/gmail=remote url=%s",
        config.mcp_server_url,
    )
    return HybridBookingTools(local_calendar=local, remote=remote, config=config)


def build_phase4_side_effects(
    config: Optional[GoogleMcpConfig] = None,
    *,
    clients: Optional[GoogleWorkspaceClients] = None,
    remote: Optional[RemoteMcpClient] = None,
    correlation_id: Optional[str] = None,
) -> Phase4SideEffects:
    """Build booking (Gemini) + waitlist (direct Gmail draft) on shared hybrid tools."""
    config = config or GoogleMcpConfig.from_env()
    tools = _build_hybrid_tools(
        config, clients=clients, remote=remote, correlation_id=correlation_id
    )
    agent = GeminiBookingAgent(tools=tools, config=config)
    primary = ExecuteBookingSideEffects(agent)
    direct = DirectBookingSideEffects(tools=tools, config=config)
    degraded = GmailOnlyDegradedQueue(tools=tools, config=config)
    return Phase4SideEffects(
        booking=ResilientBookingSideEffects(primary, degraded, direct=direct),
        waitlist=ExecuteWaitlistSideEffects(tools=tools, config=config),
        cancel=ExecuteCancelSideEffects(tools=tools, config=config),
        reschedule=ExecuteRescheduleSideEffects(tools=tools, config=config),
        tools=tools,
    )


def build_execute_booking_side_effects(
    config: Optional[GoogleMcpConfig] = None,
    *,
    clients: Optional[GoogleWorkspaceClients] = None,
    remote: Optional[RemoteMcpClient] = None,
    correlation_id: Optional[str] = None,
) -> Any:
    """
    Build Phase 4 booking use case (Gemini → hybrid tools + degraded Gmail fallback).

    Prefer ``build_phase4_side_effects`` when waitlist is also needed.
    """
    return build_phase4_side_effects(
        config,
        clients=clients,
        remote=remote,
        correlation_id=correlation_id,
    ).booking


def build_execute_waitlist_side_effects(
    config: Optional[GoogleMcpConfig] = None,
    *,
    clients: Optional[GoogleWorkspaceClients] = None,
    remote: Optional[RemoteMcpClient] = None,
    correlation_id: Optional[str] = None,
) -> ExecuteWaitlistSideEffects:
    return build_phase4_side_effects(
        config,
        clients=clients,
        remote=remote,
        correlation_id=correlation_id,
    ).waitlist
