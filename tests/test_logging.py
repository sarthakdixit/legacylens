"""Tests for secret redaction in logging (B1 requirement)."""

from __future__ import annotations

import logging

from legacylens.logging_setup import SecretRedactingFilter


def _redact(message: str) -> str:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)
    SecretRedactingFilter().filter(record)
    return record.getMessage()


def test_redacts_bearer_token():
    out = _redact("Authorization: Bearer sk-abcdef123456 sent")
    assert "sk-abcdef123456" not in out
    assert "REDACTED" in out


def test_redacts_api_key_assignment():
    out = _redact('calling with api_key=supersecretvalue now')
    assert "supersecretvalue" not in out
    assert "REDACTED" in out


def test_redacts_sk_token_anywhere():
    out = _redact("leaked sk-1234567890ABCDEF in payload")
    assert "sk-1234567890ABCDEF" not in out


def test_leaves_clean_message_untouched():
    assert _redact("parsed 12 COBOL programs") == "parsed 12 COBOL programs"
