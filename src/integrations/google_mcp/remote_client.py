"""
Streamable-HTTP MCP client for the Railway gmail-docs server.

Auth: Authorization: Bearer <MCP_HTTP_BEARER_TOKEN>
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RemoteMcpError(RuntimeError):
    pass


class RemoteMcpClient:
    def __init__(
        self,
        url: str,
        bearer_token: str,
        *,
        timeout_s: float = 30.0,
        protocol_version: str = "2024-11-05",
    ) -> None:
        if not url:
            raise ValueError("MCP server URL is required")
        if not bearer_token:
            raise ValueError("MCP bearer token is required")
        self._url = url
        self._token = bearer_token
        self._timeout_s = timeout_s
        self._protocol_version = protocol_version
        self._session_id: Optional[str] = None
        self._initialized = False

    def ensure_initialized(self) -> Dict[str, Any]:
        if self._initialized:
            return {}
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "advisor-appointment-scheduler", "version": "0.4.0"},
            },
            id_=1,
        )
        # notifications/initialized (no response id)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        result = self._rpc("tools/list", {}, id_=2)
        return list(result.get("tools") or [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        self.ensure_initialized()
        result = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            id_=3,
        )
        # MCP tools/call returns { content: [...], isError?: bool }
        if isinstance(result, dict) and result.get("isError"):
            text = _content_text(result)
            raise RemoteMcpError(text or f"Remote tool {name} returned isError")
        return result

    def _rpc(self, method: str, params: Dict[str, Any], *, id_: int) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
        status, headers, body = self._post(payload)
        if status not in (200, 202):
            raise RemoteMcpError(f"MCP HTTP {status}: {body[:300]}")
        session = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        if session:
            self._session_id = session
        msg = _parse_rpc_message(body)
        if not msg:
            raise RemoteMcpError(f"Unparseable MCP response: {body[:300]}")
        if msg.get("error"):
            err = msg["error"]
            raise RemoteMcpError(
                f"MCP error {err.get('code')}: {err.get('message')}"
            )
        result = msg.get("result")
        if not isinstance(result, dict):
            return {"value": result}
        return result

    def _post(self, payload: Dict[str, Any]) -> tuple[int, Dict[str, str], str]:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._token}",
            "MCP-Protocol-Version": self._protocol_version,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = urllib.request.Request(self._url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, {k: v for k, v in resp.headers.items()}, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.warning("remote_mcp HTTP %s method=%s", exc.code, payload.get("method"))
            return exc.code, {k: v for k, v in exc.headers.items()}, body


def _parse_rpc_message(body: str) -> Optional[Dict[str, Any]]:
    text = (body or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
    last: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                last = obj
    return last


def _content_text(result: Dict[str, Any]) -> str:
    parts = result.get("content") or []
    chunks: List[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            chunks.append(str(part.get("text") or ""))
    return "\n".join(chunks).strip()
