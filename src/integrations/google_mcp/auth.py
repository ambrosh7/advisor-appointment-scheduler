"""Google API credentials (OAuth installed-app or service account)."""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from integrations.google_mcp.config import GoogleMcpConfig

logger = logging.getLogger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/gmail.compose",
)


def load_credentials(
    config: Optional[GoogleMcpConfig] = None,
    scopes: Sequence[str] = SCOPES,
):
    """Return google.oauth2 credentials for Calendar / Docs / Gmail."""
    config = config or GoogleMcpConfig.from_env()

    sa = config.service_account_file
    if sa and str(sa) not in ("", ".") and sa.is_file():
        from google.oauth2 import service_account

        logger.info("Using Google service account credentials")
        return service_account.Credentials.from_service_account_file(
            str(sa),
            scopes=list(scopes),
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    token_path = config.oauth_token_path
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), list(scopes))

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        return creds

    if creds and creds.valid:
        return creds

    if not config.oauth_client_secrets.exists():
        raise FileNotFoundError(
            f"OAuth client secrets not found at {config.oauth_client_secrets}. "
            "Place credentials.json or set GOOGLE_SERVICE_ACCOUNT_FILE."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.oauth_client_secrets), list(scopes)
    )
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    logger.info("Stored OAuth token at %s", token_path)
    return creds
