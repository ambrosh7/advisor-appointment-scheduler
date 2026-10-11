"""Vapi custom-LLM adapter maps utterances to Orchestrator."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.chat.app import create_app
from integrations.vapi.adapter import (
    CallSessionMap,
    extract_call_id,
    last_user_text,
    openai_completion_payload,
    run_turn,
)
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore


def _orch() -> Orchestrator:
    return Orchestrator(session_store=InMemorySessionStore())


def test_extract_call_id_and_user_text():
    body = {
        "call": {"id": "call-abc"},
        "messages": [
            {"role": "system", "content": "x"},
            {"role": "user", "content": "I understand"},
        ],
    }
    assert extract_call_id(body) == "call-abc"
    assert last_user_text(body["messages"]) == "I understand"


def test_run_turn_persists_call_session():
    orch = _orch()
    mapping = CallSessionMap()
    body = {
        "call": {"id": "c1"},
        "messages": [{"role": "user", "content": "yes I understand"}],
    }
    reply = run_turn(orch, mapping, body)
    assert mapping.get("c1")
    assert reply
    # Same call continues in the same orchestrator session
    body2 = {
        "call": {"id": "c1"},
        "messages": [
            {"role": "user", "content": "yes I understand"},
            {"role": "assistant", "content": reply},
            {"role": "user", "content": "book new"},
        ],
    }
    reply2 = run_turn(orch, mapping, body2)
    assert mapping.get("c1")
    assert reply2


def test_openai_payload_shape():
    p = openai_completion_payload("Hello")
    assert p["object"] == "chat.completion"
    assert p["choices"][0]["message"]["content"] == "Hello"


def test_http_custom_llm_endpoint():
    client = TestClient(create_app(_orch(), enable_ttl_job=False))
    r = client.get("/voice/config")
    assert r.status_code == 200
    assert r.json()["mode"] == "voice_agent"
    assert r.json()["vapi_custom_llm_path"] == "/v1/chat/completions"
    assert "elevenlabs_agent_id" in r.json()
    assert r.json()["custom_llm_base_url"] == "/v1"

    r = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "I understand"}],
            "call": {"id": "http-1"},
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"]
