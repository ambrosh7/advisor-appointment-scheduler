"""
Vapi custom-LLM adapter — OpenAI-compatible /chat/completions.

Vapi owns mic / phone / STT / TTS. This adapter maps each user utterance to
``Orchestrator.handle`` and returns assistant text. Booking logic stays here.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from session.orchestrator import Orchestrator


@dataclass
class CallSessionMap:
    """Map Vapi call ids → orchestrator session ids."""

    by_call: Dict[str, str] = field(default_factory=dict)

    def get(self, call_id: str) -> Optional[str]:
        return self.by_call.get(call_id)

    def put(self, call_id: str, session_id: str) -> None:
        self.by_call[call_id] = session_id


def extract_call_id(body: dict) -> str:
    call = body.get("call") or {}
    if isinstance(call, dict) and call.get("id"):
        return str(call["id"])
    meta = body.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("callId", "call_id", "session_id"):
            if meta.get(key):
                return str(meta[key])
    return str(body.get("user") or body.get("conversationId") or "anon")


def last_user_text(messages: List[dict]) -> Optional[str]:
    for msg in reversed(messages or []):
        if (msg.get("role") or "").lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            joined = " ".join(p for p in parts if p).strip()
            if joined:
                return joined
    return None


def ensure_session(
    orch: Orchestrator,
    mapping: CallSessionMap,
    call_id: str,
) -> tuple[str, List[str], bool]:
    """
    Return (session_id, opening_messages, created_now).

    Opening messages are non-empty only when the session was just created.
    """
    existing = mapping.get(call_id)
    if existing:
        session = orch.store.get(existing)
        if session is not None:
            return existing, [], False
    turn = orch.create_session()
    mapping.put(call_id, turn.session_id)
    return turn.session_id, list(turn.messages), True


def run_turn(
    orch: Orchestrator,
    mapping: CallSessionMap,
    body: dict,
) -> str:
    call_id = extract_call_id(body)
    messages = body.get("messages") or []
    user_text = last_user_text(messages)
    session_id, opening, created = ensure_session(orch, mapping, call_id)
    session = orch.store.get(session_id)
    if session is None:
        turn = orch.create_session()
        mapping.put(call_id, turn.session_id)
        return "\n\n".join(turn.messages)

    if user_text is None:
        if created and opening:
            return "\n\n".join(opening)
        return "I'm ready when you are — you can book, reschedule, cancel, or check availability."

    # First user turn after create: opening already spoken by Vapi firstMessage;
    # still process the utterance normally.
    turn = orch.handle(user_text, session)
    reply = "\n\n".join(turn.messages).strip()
    return reply or "Okay."


def openai_completion_payload(text: str, *, model: str = "advisor-orchestrator") -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def openai_sse_chunks(text: str, *, model: str = "advisor-orchestrator") -> Iterator[str]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    # Emit in sentence-ish chunks for natural TTS pacing
    parts = _chunk_text(text)
    for i, part in enumerate(parts):
        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": part}
                    if i == 0
                    else {"content": part},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(payload)}\n\n"
    final = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


def _chunk_text(text: str, size: int = 80) -> List[str]:
    if not text:
        return [""]
    chunks: List[str] = []
    buf = ""
    for word in text.split(" "):
        nxt = word if not buf else f"{buf} {word}"
        if len(nxt) > size and buf:
            chunks.append(buf + " ")
            buf = word
        else:
            buf = nxt
    if buf:
        chunks.append(buf)
    return chunks
