"""Logging configuration for legacylens.

Two distinct streams:

* **Console logging** — human-facing progress/diagnostics via rich, controlled by
  ``--verbose``. Goes to stderr so it never pollutes machine-readable stdout.
* **Audit log** — a separate, append-only, structured record of what a run did
  (see :mod:`legacylens.audit_log`). The audit log is the compliance artifact;
  console logging is convenience.

Both pass through :class:`SecretRedactingFilter` so credentials are never written.
"""

from __future__ import annotations

import logging
import re

from rich.logging import RichHandler

LOGGER_NAME = "legacylens"

# Patterns that look like secrets; redacted before any record is emitted.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*)([^\s,;}\"']+)"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)(\S+)"),
    re.compile(r"(sk-[A-Za-z0-9]{8,})"),
]
_REDACTED = "***REDACTED***"


class SecretRedactingFilter(logging.Filter):
    """Scrub anything resembling a credential from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            if pattern.groups >= 2:
                msg = pattern.sub(lambda m: m.group(1) + _REDACTED, msg)
            else:
                msg = pattern.sub(_REDACTED, msg)
        record.msg = msg
        record.args = ()
        return True


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure and return the root legacylens logger."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    handler = RichHandler(
        show_time=False,
        show_path=False,
        rich_tracebacks=False,
        markup=False,
    )
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler.addFilter(SecretRedactingFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
