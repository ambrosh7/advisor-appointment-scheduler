"""Redaction + ops config."""

from __future__ import annotations

from ops.config import OpsConfig
from ops.logging import redact_for_prod, redact_user_text


def test_redact_masks_email_and_phone() -> None:
    text = "reach me at user@example.com or +91 98765 43210"
    out = redact_user_text(text)
    assert "user@example.com" not in out
    assert "[REDACTED]" in out


def test_redact_for_prod_hides_raw_utterance() -> None:
    cfg = OpsConfig(app_env="production", redact_user_text=True)
    out = redact_for_prod("book new tomorrow", config=cfg)
    assert "book new" not in out
    assert "len=" in out


def test_redact_for_dev_keeps_text_with_pii_mask() -> None:
    cfg = OpsConfig(app_env="development", redact_user_text=False)
    out = redact_for_prod("topic kyc", config=cfg)
    assert out == "topic kyc"
