"""Environment-driven Google / booking / remote MCP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _materialize_service_account_file() -> str:
    """
    Prefer GOOGLE_SERVICE_ACCOUNT_FILE path.

    On Render/Cloud, paste the JSON into GOOGLE_SERVICE_ACCOUNT_JSON and we
    write it to a temp file at boot.
    """
    path = _env("GOOGLE_SERVICE_ACCOUNT_FILE")
    raw = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return path
    target = Path(path) if path else Path("/tmp/google-service-account.json")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw, encoding="utf-8")
        return str(target)
    except OSError:
        return path


@dataclass(frozen=True)
class GoogleMcpConfig:
    gemini_api_key: str
    gemini_model: str
    calendar_id: str
    docs_prebooking_id: str
    gmail_advisor_to: str
    secure_link_template: str
    oauth_client_secrets: Path
    oauth_token_path: Path
    service_account_file: Path
    mcp_server_url: str
    mcp_bearer_token: str
    advice_educational_url: str = "https://example.com/learn/basics"
    correlation_header: str = "X-Correlation-Id"

    @classmethod
    def from_env(cls) -> "GoogleMcpConfig":
        sa_raw = _materialize_service_account_file()
        return cls(
            gemini_api_key=_env("GEMINI_API_KEY"),
            gemini_model=_env("GEMINI_MODEL", "gemini-3.8-flash"),
            calendar_id=_env("GOOGLE_CALENDAR_ID", "primary"),
            docs_prebooking_id=_env("GOOGLE_DOCS_PREBOOKING_ID"),
            gmail_advisor_to=_env("GOOGLE_GMAIL_ADVISOR_TO"),
            secure_link_template=_env(
                "SECURE_LINK_TEMPLATE",
                "https://example.com/complete?ref={code}",
            ),
            oauth_client_secrets=Path(
                _env("GOOGLE_CLIENT_SECRETS", "credentials.json")
            ),
            oauth_token_path=Path(_env("GOOGLE_TOKEN_PATH", "token.json")),
            service_account_file=Path(sa_raw) if sa_raw else Path(""),
            mcp_server_url=_env(
                "MCP_SERVER_URL",
                "https://gmail-docs-mcp-server-production.up.railway.app/mcp",
            ),
            mcp_bearer_token=(
                _env("MCP_HTTP_BEARER_TOKEN")
                or _env("MCP_AUTH_TOKEN")
                or _env("MCP_TOKEN")
            ),
            advice_educational_url=_env(
                "ADVICE_EDUCATIONAL_URL",
                "https://example.com/learn/basics",
            ),
        )

    def secure_link_for(self, code: str) -> str:
        tpl = self.secure_link_template
        if "{code}" in tpl:
            return tpl.format(code=code)
        sep = "&" if "?" in tpl else "?"
        return f"{tpl}{sep}ref={code}"

    @property
    def hybrid_remote_enabled(self) -> bool:
        return bool(self.mcp_server_url and self.mcp_bearer_token)

    def validate_for_live(self) -> list[str]:
        """
        Hybrid Phase 4:
        - Gemini for tool-calling
        - Local Google auth for Calendar
        - Railway MCP bearer for Docs + Gmail
        """
        errors: list[str] = []
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY is required")
        if not self.docs_prebooking_id:
            errors.append("GOOGLE_DOCS_PREBOOKING_ID is required")
        if not self.gmail_advisor_to:
            errors.append("GOOGLE_GMAIL_ADVISOR_TO is required")
        if not self.mcp_bearer_token:
            errors.append(
                "MCP_HTTP_BEARER_TOKEN (or MCP_AUTH_TOKEN) is required for Railway Docs/Gmail"
            )
        sa = self.service_account_file
        has_sa = bool(sa and str(sa) not in ("", ".") and sa.exists())
        has_oauth = self.oauth_client_secrets.exists() or self.oauth_token_path.exists()
        if not has_sa and not has_oauth:
            errors.append(
                "Google Calendar auth missing: set GOOGLE_SERVICE_ACCOUNT_FILE or OAuth "
                "GOOGLE_CLIENT_SECRETS / GOOGLE_TOKEN_PATH"
            )
        return errors
