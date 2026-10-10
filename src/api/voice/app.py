"""
Voice WebSocket surface — audio/text utterances → same Orchestrator.handle.

Protocol (JSON text frames unless noted):

  Client → server
    {"type": "start"}
    {"type": "audio_chunk", "pcm16_b64": "..."}
    {"type": "speech_start"}
    {"type": "utterance_end"}
    {"type": "text_utterance", "text": "yes"}

  Server → client
    {"type": "session_started", ...}
    {"type": "partial_transcript", "text"}
    {"type": "final_transcript", "text"}
    {"type": "assistant_turn", ...}
    {"type": "tts_cancelled"}
    {"type": "error", "detail"}
    {"type": "rate_limited", "retry_after_s"}
"""

from __future__ import annotations

import base64
import json
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from api.voice.session import VoiceConnection
from domain.calendar import MockCalendarService
from domain.clock import SystemClock
from integrations.booking_agent.factory import build_phase4_side_effects
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.voice.audio_io import MemoryAudioIO
from integrations.voice.pipeline import VoicePipeline
from integrations.voice.stt import PassthroughSpeechToText
from integrations.voice.tts import RecordingTextToSpeech
from nlu.engine import build_default_nlu_engine
from ops.config import OpsConfig
from ops.logging import bind_context, configure_logging, redact_for_prod
from ops.rate_limit import SlidingWindowRateLimiter
from ops.ttl_job import SessionTtlJob
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore

logger = logging.getLogger(__name__)


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


def _default_orchestrator(ops: OpsConfig) -> Orchestrator:
    clock = SystemClock()
    config = GoogleMcpConfig.from_env()
    phase4 = _try_build_phase4(config)
    return Orchestrator(
        session_store=InMemorySessionStore(
            ttl=timedelta(minutes=ops.session_ttl_minutes)
        ),
        calendar=MockCalendarService(),
        nlu=build_default_nlu_engine(clock=clock),
        clock=clock,
        booking_side_effects=phase4.booking if phase4 else None,
        waitlist_side_effects=phase4.waitlist if phase4 else None,
        cancel_side_effects=phase4.cancel if phase4 else None,
        reschedule_side_effects=phase4.reschedule if phase4 else None,
        google_config=config,
    )


def _turn_payload(result) -> dict[str, Any]:
    return {
        "messages": result.messages,
        "spoken": result.spoken_messages,
        "state": result.state.value,
        "session_id": result.session_id,
        "barge_in": result.barge_in,
        "latency_ms": {
            "stt": round(result.latency.stt_ms, 2),
            "orchestrator": round(result.latency.orchestrator_ms, 2),
            "tts": round(result.latency.tts_ms, 2),
            "total": round(result.latency.total_ms, 2),
        },
        "audio_bytes_played": result.audio_bytes_played,
    }


def create_app(
    orchestrator: Optional[Orchestrator] = None,
    *,
    ops_config: Optional[OpsConfig] = None,
    enable_ttl_job: Optional[bool] = None,
) -> FastAPI:
    ops = ops_config or OpsConfig.from_env()
    configure_logging(ops)
    orch = orchestrator or _default_orchestrator(ops)
    rate_limiter = SlidingWindowRateLimiter(
        limit=ops.session_create_rate_limit,
        window_s=ops.session_create_rate_window_s,
    )
    ttl_job = SessionTtlJob(
        orch.store,
        interval_s=ops.ttl_sweep_interval_s,
        name="voice-session-ttl",
    )
    run_ttl = ops.enable_ttl_job if enable_ttl_job is None else enable_ttl_job

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_ttl:
            ttl_job.start()
        yield
        ttl_job.stop()

    app = FastAPI(
        title="Advisor Appointment Scheduler — Voice",
        version="0.8.0",
        lifespan=lifespan,
    )
    app.state.orchestrator = orch
    app.state.ops_config = ops
    app.state.rate_limiter = rate_limiter
    app.state.ttl_job = ttl_job

    @app.get("/health")
    def health() -> dict:
        job: SessionTtlJob = app.state.ttl_job
        return {
            "status": "ok",
            "surface": "voice",
            "phase7_voice": True,
            "phase8_ttl_job": job.running,
            "phase8_redact_user_text": ops.redact_user_text,
            "ws_path": "/ws/voice",
        }

    @app.websocket("/ws/voice")
    async def voice_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        stt = PassthroughSpeechToText()
        tts = RecordingTextToSpeech()
        audio = MemoryAudioIO()
        pipeline = VoicePipeline(orch, stt=stt, tts=tts, audio_io=audio)
        conn = VoiceConnection(pipeline=pipeline)
        client_host = websocket.client.host if websocket.client else "global"

        async def send(payload: dict) -> None:
            await websocket.send_text(json.dumps(payload))

        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break

                if "bytes" in message and message["bytes"] is not None:
                    partial = pipeline.feed_audio(message["bytes"])
                    conn.note_partial(partial)
                    if pipeline.tts.cancelled:
                        await send({"type": "tts_cancelled"})
                    if partial is not None:
                        await send({"type": "partial_transcript", "text": partial})
                    continue

                raw = message.get("text")
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await send({"type": "error", "detail": "invalid JSON"})
                    continue

                msg_type = data.get("type")
                if msg_type == "start":
                    decision = rate_limiter.allow(f"voice:{client_host}")
                    if not decision.allowed:
                        await send(
                            {
                                "type": "rate_limited",
                                "retry_after_s": round(decision.retry_after_s, 1),
                            }
                        )
                        continue
                    result = pipeline.start_session()
                    conn.session_id = result.session_id
                    logger.info(
                        "voice_session_started",
                        extra=bind_context(
                            session_id=result.session_id,
                            event="session_created",
                            surface="voice",
                        ),
                    )
                    await send({"type": "session_started", **_turn_payload(result)})
                    continue

                if msg_type == "speech_start":
                    pipeline.on_speech_start()
                    await send({"type": "tts_cancelled"})
                    continue

                if msg_type == "audio_chunk":
                    b64 = data.get("pcm16_b64") or ""
                    try:
                        pcm = base64.b64decode(b64) if b64 else b""
                    except Exception:  # noqa: BLE001
                        await send({"type": "error", "detail": "bad pcm16_b64"})
                        continue
                    partial = pipeline.feed_audio(pcm)
                    conn.note_partial(partial)
                    if pipeline.tts.cancelled:
                        await send({"type": "tts_cancelled"})
                    if partial is not None:
                        await send({"type": "partial_transcript", "text": partial})
                    continue

                if msg_type == "utterance_end":
                    result = pipeline.commit_utterance()
                    logger.info(
                        "voice_utterance final=%s",
                        redact_for_prod(result.final_transcript, config=ops),
                        extra=bind_context(
                            session_id=result.session_id,
                            state=result.state.value,
                            event="voice_utterance",
                            surface="voice",
                        ),
                    )
                    await send(
                        {
                            "type": "final_transcript",
                            "text": result.final_transcript,
                        }
                    )
                    await send({"type": "assistant_turn", **_turn_payload(result)})
                    continue

                if msg_type == "text_utterance":
                    text = (data.get("text") or "").strip()
                    result = pipeline.commit_utterance(text)
                    logger.info(
                        "voice_text_utterance final=%s",
                        redact_for_prod(result.final_transcript, config=ops),
                        extra=bind_context(
                            session_id=result.session_id,
                            state=result.state.value,
                            event="voice_utterance",
                            surface="voice",
                        ),
                    )
                    await send(
                        {
                            "type": "final_transcript",
                            "text": result.final_transcript,
                        }
                    )
                    await send({"type": "assistant_turn", **_turn_payload(result)})
                    continue

                await send({"type": "error", "detail": f"unknown type: {msg_type}"})
        except WebSocketDisconnect:
            logger.info("voice ws disconnected session_id=%s", conn.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("voice ws error")
            try:
                await send({"type": "error", "detail": str(exc)})
            except Exception:  # noqa: BLE001
                pass

    return app


app = create_app()
