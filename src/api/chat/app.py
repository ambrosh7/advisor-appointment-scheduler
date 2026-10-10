"""
HTTP chat API.

  POST /session              → { session_id, messages, state }
  POST /session/{id}/message → { messages, state }
  GET  /session/{id}         → debug state
  GET  /health
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from domain.calendar import MockCalendarService
from domain.clock import SystemClock
from integrations.booking_agent.factory import build_phase4_side_effects
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.vapi.adapter import (
    CallSessionMap,
    openai_completion_payload,
    openai_sse_chunks,
    run_turn,
)
from nlu.engine import build_default_nlu_engine
from ops.config import OpsConfig
from ops.logging import bind_context, configure_logging, redact_for_prod
from ops.rate_limit import SlidingWindowRateLimiter
from ops.ttl_job import SessionTtlJob
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parents[3] / "web"


class MessageIn(BaseModel):
    text: str = Field(..., min_length=0)


class TurnOut(BaseModel):
    messages: List[str]
    state: str
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None


def _try_build_phase4(config: GoogleMcpConfig):
    errors = config.validate_for_live()
    if errors:
        logger.warning("Phase 4/5 side effects not wired: %s", "; ".join(errors))
        return None
    try:
        return build_phase4_side_effects(config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to initialize Google MCP / Gemini agent: %s", exc)
        return None


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or "global"
    return "global"


def create_app(
    orchestrator: Optional[Orchestrator] = None,
    *,
    ops_config: Optional[OpsConfig] = None,
    enable_ttl_job: Optional[bool] = None,
) -> FastAPI:
    ops = ops_config or OpsConfig.from_env()
    configure_logging(ops)
    clock = SystemClock()
    config = GoogleMcpConfig.from_env()

    if orchestrator is None:
        store = InMemorySessionStore(ttl=timedelta(minutes=ops.session_ttl_minutes))
        phase4 = _try_build_phase4(config)
        orchestrator = Orchestrator(
            session_store=store,
            calendar=MockCalendarService(),
            nlu=build_default_nlu_engine(clock=clock),
            clock=clock,
            booking_side_effects=phase4.booking if phase4 else None,
            waitlist_side_effects=phase4.waitlist if phase4 else None,
            cancel_side_effects=phase4.cancel if phase4 else None,
            reschedule_side_effects=phase4.reschedule if phase4 else None,
            google_config=config,
        )

    rate_limiter = SlidingWindowRateLimiter(
        limit=ops.session_create_rate_limit,
        window_s=ops.session_create_rate_window_s,
    )
    ttl_job = SessionTtlJob(
        orchestrator.store,
        interval_s=ops.ttl_sweep_interval_s,
        name="chat-session-ttl",
    )
    run_ttl = ops.enable_ttl_job if enable_ttl_job is None else enable_ttl_job

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_ttl:
            ttl_job.start()
        yield
        ttl_job.stop()

    app = FastAPI(
        title="Advisor Appointment Scheduler",
        version="0.8.0",
        lifespan=lifespan,
    )
    app.state.orchestrator = orchestrator
    app.state.ops_config = ops
    app.state.rate_limiter = rate_limiter
    app.state.ttl_job = ttl_job
    app.state.vapi_sessions = CallSessionMap()

    cors_raw = (os.getenv("CORS_ORIGINS") or "*").strip()
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()] or ["*"]
    # Browsers reject allow_origins=["*"] with allow_credentials=True.
    allow_credentials = cors_origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if _WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")

        @app.get("/")
        def frontend_index() -> FileResponse:
            return FileResponse(_WEB_DIR / "index.html")

    @app.get("/health")
    def health() -> dict:
        orch: Orchestrator = app.state.orchestrator
        job: SessionTtlJob = app.state.ttl_job
        return {
            "status": "ok",
            "app_env": ops.app_env,
            "phase4_side_effects": orch._side_effects is not None,  # noqa: SLF001
            "phase5_waitlist": orch._waitlist_side_effects is not None,  # noqa: SLF001
            "phase6_cancel": orch._cancel_side_effects is not None,  # noqa: SLF001
            "phase6_reschedule": orch._reschedule_side_effects is not None,  # noqa: SLF001
            "phase8_ttl_job": job.running,
            "phase8_redact_user_text": ops.redact_user_text,
            "phase7_vapi_custom_llm": True,
            "sessions": len(orch.store) if hasattr(orch.store, "__len__") else None,
        }

    @app.get("/voice/config")
    def voice_config() -> dict:
        """Public voice client config (no secrets)."""
        return {
            "mode": "voice_agent",
            "browser_speech": True,
            "vapi_public_key": (os.getenv("VAPI_PUBLIC_KEY") or "").strip() or None,
            "vapi_assistant_id": (os.getenv("VAPI_ASSISTANT_ID") or "").strip() or None,
            "vapi_custom_llm_path": "/v1/chat/completions",
            "hint": (
                "Browser mic uses Web Speech API locally. "
                "Point Vapi custom-LLM base URL at this server /v1 for phone/WebRTC."
            ),
        }

    @app.post("/v1/chat/completions")
    async def vapi_custom_llm(request: Request):
        """
        OpenAI-compatible completions for Vapi custom-LLM provider.

        Configure Vapi assistant model.provider=custom-llm and
        model.url=https://<host>/v1 (Vapi appends /chat/completions).
        """
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

        orch: Orchestrator = app.state.orchestrator
        mapping: CallSessionMap = app.state.vapi_sessions
        reply = run_turn(orch, mapping, body if isinstance(body, dict) else {})
        stream = bool((body or {}).get("stream"))
        model = str((body or {}).get("model") or "advisor-orchestrator")
        logger.info(
            "vapi_custom_llm stream=%s reply_len=%s",
            stream,
            len(reply),
            extra=bind_context(event="vapi_turn", surface="vapi"),
        )
        if stream:
            return StreamingResponse(
                openai_sse_chunks(reply, model=model),
                media_type="text/event-stream",
            )
        return openai_completion_payload(reply, model=model)

    @app.post("/session", response_model=TurnOut)
    def create_session(request: Request) -> TurnOut:
        key = _client_key(request)
        decision = rate_limiter.allow(key)
        if not decision.allowed:
            logger.warning(
                "session_create_rate_limited key=%s retry_after_s=%.1f",
                key,
                decision.retry_after_s,
                extra=bind_context(event="rate_limited", surface="chat"),
            )
            raise HTTPException(
                status_code=429,
                detail="Too many sessions created; try again shortly.",
                headers={"Retry-After": str(max(1, int(decision.retry_after_s)))},
            )
        turn = orchestrator.create_session()
        session = orchestrator.store.get(turn.session_id)
        corr = session.correlation_id if session else str(uuid4())
        logger.info(
            "session_created",
            extra=bind_context(
                correlation_id=corr,
                session_id=turn.session_id,
                event="session_created",
                surface="chat",
            ),
        )
        return TurnOut(
            messages=turn.messages,
            state=turn.state.value,
            session_id=turn.session_id,
            correlation_id=corr,
        )

    @app.post("/session/{session_id}/message", response_model=TurnOut)
    def post_message(session_id: str, body: MessageIn, request: Request) -> TurnOut:
        session = orchestrator.store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found or expired")
        corr = request.headers.get("x-correlation-id") or session.correlation_id
        session.correlation_id = corr
        logger.info(
            "http_message user_text=%s",
            redact_for_prod(body.text, config=ops),
            extra=bind_context(
                correlation_id=corr,
                session_id=session_id,
                state=session.state.value,
                event="http_message",
                surface="chat",
            ),
        )
        turn = orchestrator.handle(body.text, session)
        return TurnOut(
            messages=turn.messages,
            state=turn.state.value,
            session_id=session_id,
            correlation_id=corr,
        )

    @app.get("/session/{session_id}")
    def get_session(session_id: str) -> dict:
        session = orchestrator.store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found or expired")
        return session.to_debug_dict()

    return app


app = create_app()
