"""Exception hierarchy for legacylens.

All errors raised intentionally by the tool derive from ``LegacyLensError`` so the
CLI can present them cleanly (non-zero exit, no traceback) while unexpected errors
still surface a full traceback for debugging.
"""

from __future__ import annotations


class LegacyLensError(Exception):
    """Base class for all expected, user-facing errors."""

    exit_code: int = 1


class ConfigError(LegacyLensError):
    """Raised when a configuration file is missing, malformed, or invalid."""

    exit_code = 2


class AirGapViolationError(LegacyLensError):
    """Raised when an operation would contact a network endpoint not permitted
    by the configured air-gap policy."""

    exit_code = 3


class BudgetExceededError(LegacyLensError):
    """Raised when a run would exceed its configured token budget."""

    exit_code = 5


class FindingsGateError(LegacyLensError):
    """Raised when findings meet/exceed the configured --fail-on threshold.

    Distinct exit code so CI can tell a policy gate failure apart from a tool error.
    """

    exit_code = 6
