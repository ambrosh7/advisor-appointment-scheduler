"""Process-level ops settings (env-driven)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class OpsConfig:
    """Hardening knobs shared by chat and voice."""

    app_env: str = "development"
    redact_user_text: bool = False
    session_create_rate_limit: int = 30
    session_create_rate_window_s: float = 60.0
    session_ttl_minutes: int = 30
    ttl_sweep_interval_s: float = 60.0
    enable_ttl_job: bool = True
    log_json: bool = False

    @classmethod
    def from_env(cls) -> "OpsConfig":
        app_env = _env("APP_ENV", "development").lower() or "development"
        prod = app_env in {"prod", "production"}
        redact_flag = _env("REDACT_USER_TEXT").lower()
        if redact_flag in {"1", "true", "yes", "on"}:
            redact = True
        elif redact_flag in {"0", "false", "no", "off"}:
            redact = False
        else:
            redact = prod
        log_json_flag = _env("LOG_JSON").lower()
        if log_json_flag in {"1", "true", "yes", "on"}:
            log_json = True
        elif log_json_flag in {"0", "false", "no", "off"}:
            log_json = False
        else:
            log_json = prod
        ttl_job_flag = _env("ENABLE_TTL_JOB", "1").lower()
        return cls(
            app_env=app_env,
            redact_user_text=redact,
            session_create_rate_limit=_env_int("SESSION_CREATE_RATE_LIMIT", 30),
            session_create_rate_window_s=_env_float("SESSION_CREATE_RATE_WINDOW_S", 60.0),
            session_ttl_minutes=_env_int("SESSION_TTL_MINUTES", 30),
            ttl_sweep_interval_s=_env_float("TTL_SWEEP_INTERVAL_S", 60.0),
            enable_ttl_job=ttl_job_flag not in {"0", "false", "no", "off"},
            log_json=log_json,
        )

    @property
    def is_production(self) -> bool:
        return self.app_env in {"prod", "production"}
