"""
Injectable Google API service doubles for tests.

These replace googleapiclient service objects — not FakeMCP. MCP tool functions
still run through ``GoogleMcpTools``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _Exec:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def execute(self) -> Any:
        return self._payload


class RecordingCalendar:
    def __init__(self) -> None:
        self.events_created: List[dict] = []
        self.deleted: List[str] = []
        self._seq = 0

    def events(self) -> "RecordingCalendar":
        return self

    def insert(self, calendarId: str, body: dict) -> _Exec:
        self._seq += 1
        event_id = f"evt-{self._seq}"
        self.events_created.append({"calendarId": calendarId, "body": body, "id": event_id})
        return _Exec({"id": event_id})

    def delete(self, calendarId: str, eventId: str) -> _Exec:
        self.deleted.append(eventId)
        return _Exec(None)

    def list(self, **kwargs: Any) -> _Exec:
        return _Exec({"items": []})


class RecordingDocs:
    def __init__(self) -> None:
        self.appended: List[dict] = []
        self.fail_remaining: int = 0

    def documents(self) -> "RecordingDocs":
        return self

    def get(self, documentId: str) -> _Exec:
        return _Exec({"body": {"content": [{"endIndex": 2}]}})

    def batchUpdate(self, documentId: str, body: dict) -> _Exec:
        if self.fail_remaining > 0:
            self.fail_remaining -= 1
            raise RuntimeError("docs_unavailable")
        self.appended.append({"documentId": documentId, "body": body})
        return _Exec({"replies": []})


class RecordingGmail:
    def __init__(self) -> None:
        self.created_drafts: List[dict] = []
        self._seq = 0

    def users(self) -> "RecordingGmail":
        return self

    def drafts(self) -> "RecordingGmail":
        return self

    def create(self, userId: str, body: dict) -> _Exec:
        self._seq += 1
        draft_id = f"draft-{self._seq}"
        self.created_drafts.append({"userId": userId, "body": body, "id": draft_id})
        return _Exec({"id": draft_id})


def make_recording_clients(correlation_id: str = "test-corr"):
    from integrations.google_mcp.clients import GoogleWorkspaceClients

    return GoogleWorkspaceClients(
        calendar=RecordingCalendar(),
        docs=RecordingDocs(),
        gmail=RecordingGmail(),
        correlation_id=correlation_id,
    )
