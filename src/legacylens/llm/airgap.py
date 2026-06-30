"""Air-gap enforcement at the transport layer.

When ``air_gapped`` is enabled, :class:`AirGapTransport` wraps the real transport and
rejects any request whose host is not in the allow-list. The allow-list is derived
from the configured providers' endpoints, so the only way to reach a host is to
declare it in ``llm.providers``. This guarantees no code path — present or future —
can silently phone home.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..errors import AirGapViolationError
from .base import Transport


def host_of(url: str) -> str:
    """Return the lowercased host[:port] of a URL, or '' if unparseable."""
    parsed = urlparse(url)
    return (parsed.netloc or "").lower()


class AirGapTransport:
    """Transport decorator that enforces a host allow-list."""

    def __init__(self, inner: Transport, allowed_hosts: set[str]):
        self.inner = inner
        self.allowed_hosts = {h.lower() for h in allowed_hosts}

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        host = host_of(url)
        if host not in self.allowed_hosts:
            allowed = ", ".join(sorted(self.allowed_hosts)) or "(none)"
            raise AirGapViolationError(
                f"air-gap policy blocked request to '{host}'. "
                f"Allowed endpoints: {allowed}. "
                f"Add the host to llm.providers or set air_gapped: false."
            )
        return self.inner.post_json(url, headers, payload, timeout)
