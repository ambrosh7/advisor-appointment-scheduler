"""Structured logging + user-text redaction (chat and STT)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping, Optional

from ops.config import OpsConfig

# Patterns aligned with nlu.pii — never log matched values.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]*)?\d{3,5}[-.\s]?\d{4,5}"
    r"|\b\d{10}\b"
)
_ACCOUNT = re.compile(r"(?<!\d)\d{8,}(?!\d)")

REDACTED = "[REDACTED]"


def redact_user_text(text: str, *, enabled: bool = True) -> str:
    """Mask PII-like spans; in prod optionally replace the whole utterance."""
    if not enabled or not text:
        return text
    masked = _EMAIL.sub(REDACTED, text)
    masked = _PHONE.sub(REDACTED, masked)
    masked = _ACCOUNT.sub(REDACTED, masked)
    return masked


def redact_for_prod(text: str, *, config: Optional[OpsConfig] = None) -> str:
    """
    Production policy: do not persist/log raw user text (chat or STT).

    Returns a short placeholder plus length, after PII masking.
    """
    cfg = config or OpsConfig.from_env()
    if not cfg.redact_user_text:
        return redact_user_text(text, enabled=True)
    if not text:
        return ""
    masked = redact_user_text(text, enabled=True)
    return f"<user_text len={len(masked)}>"


class JsonFormatter(logging.Formatter):
    """One JSON object per log line for prod aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in (
            "correlation_id",
            "session_id",
            "state",
            "tool",
            "latency_ms",
            "surface",
            "event",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _EnsureCorrelationFilter(logging.Filter):
    """Add default correlation_id after extras are applied (never overwrite)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            setattr(record, "correlation_id", "-")
        return True


def configure_logging(config: Optional[OpsConfig] = None) -> OpsConfig:
    """Idempotent root logging setup (JSON in prod when LOG_JSON/APP_ENV say so)."""
    cfg = config or OpsConfig.from_env()
    root = logging.getLogger()
    if getattr(root, "_advisor_ops_configured", False):
        return cfg
    handler = logging.StreamHandler()
    handler.addFilter(_EnsureCorrelationFilter())
    if cfg.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] "
                "correlation_id=%(correlation_id)s %(message)s"
            )
        )
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root._advisor_ops_configured = True  # type: ignore[attr-defined]
    return cfg


def bind_context(
    extra: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> MutableMapping[str, Any]:
    """Build ``extra=`` dict for logger calls with correlation_id etc."""
    ctx: dict[str, Any] = {}
    if extra:
        ctx.update(extra)
    ctx.update(kwargs)
    if "correlation_id" not in ctx:
        ctx["correlation_id"] = "-"
    return ctx
