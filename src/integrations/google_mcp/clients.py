"""
Live Google API service objects (Calendar v3, Docs v1, Gmail v1).

Injectable for tests — inject alternate service objects, not FakeMCP tools.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from integrations.google_mcp.auth import load_credentials
from integrations.google_mcp.config import GoogleMcpConfig

logger = logging.getLogger(__name__)


class SupportsExecute(Protocol):
    def execute(self) -> Any: ...


@dataclass
class GoogleWorkspaceClients:
    calendar: Any
    docs: Any
    gmail: Any
    correlation_id: str = ""

    @classmethod
    def from_config(
        cls,
        config: Optional[GoogleMcpConfig] = None,
        *,
        correlation_id: str = "",
    ) -> "GoogleWorkspaceClients":
        config = config or GoogleMcpConfig.from_env()
        from googleapiclient.discovery import build

        creds = load_credentials(config)
        return cls(
            calendar=build("calendar", "v3", credentials=creds, cache_discovery=False),
            docs=build("docs", "v1", credentials=creds, cache_discovery=False),
            gmail=build("gmail", "v1", credentials=creds, cache_discovery=False),
            correlation_id=correlation_id,
        )


def with_retry(
    label: str,
    fn: Callable[[], Any],
    *,
    correlation_id: str = "",
    timeout_note: str = "",
    retries: int = 1,
) -> Any:
    """Execute Google API call with a single retry on transient failure."""
    last_exc: Optional[BaseException] = None
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            result = fn()
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "google_api ok tool=%s correlation_id=%s latency_ms=%s %s",
                label,
                correlation_id,
                latency_ms,
                timeout_note,
            )
            return result
        except Exception as exc:  # noqa: BLE001 — surface as tool error
            last_exc = exc
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "google_api fail tool=%s correlation_id=%s latency_ms=%s attempt=%s err=%s",
                label,
                correlation_id,
                latency_ms,
                attempt + 1,
                type(exc).__name__,
            )
            if attempt >= retries:
                break
            time.sleep(0.4)
    assert last_exc is not None
    raise last_exc
