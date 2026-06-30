"""Core LLM types and the provider/transport interfaces.

Design notes:

* **Transport seam.** Providers never call the network directly; they go through a
  :class:`Transport`. Production uses :class:`UrllibTransport` (stdlib only — no extra
  dependency to vendor for air-gapped installs). Tests inject a fake transport, and
  the gateway wraps the transport to enforce the air-gap allow-list. Because
  enforcement lives at the transport layer it catches *any* outbound URL, not just
  the ones a provider means to call.
* **Normalized responses.** Each provider maps its wire format to
  :class:`CompletionResponse` / :class:`EmbeddingResponse` so the rest of the codebase
  is provider-agnostic.
"""

from __future__ import annotations

import abc
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..errors import LegacyLensError


class LLMError(LegacyLensError):
    """Raised for provider/transport failures (bad response, HTTP error, etc.)."""

    exit_code = 4


# --------------------------------------------------------------------------- #
# Request / response value types
# --------------------------------------------------------------------------- #
@dataclass
class Message:
    """A single chat message. ``role`` is one of ``system|user|assistant``."""

    role: str
    content: str


@dataclass
class CompletionRequest:
    messages: list[Message]
    temperature: float = 0.0
    max_tokens: int = 1024
    stop: list[str] | None = None
    # Provider-specific passthrough options (merged into the request body).
    extra: dict[str, Any] = field(default_factory=dict)

    def cache_signature(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable view used for cache keying."""
        return {
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stop": self.stop,
            "extra": self.extra,
        }


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class CompletionResponse:
    text: str
    model: str
    provider: str
    usage: Usage | None = None
    cached: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingResponse:
    vectors: list[list[float]]
    model: str
    provider: str
    cached: bool = False


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
@runtime_checkable
class Transport(Protocol):
    """Minimal HTTP-JSON transport. Implementations POST ``payload`` as JSON and
    return the parsed JSON response."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        ...


class UrllibTransport:
    """Default transport built on the standard library (no third-party HTTP dep)."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        for key, value in headers.items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (url is allow-listed upstream)
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise LLMError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network path
            raise LLMError(f"could not reach {url}: {exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise LLMError(f"non-JSON response from {url}: {body[:200]}") from exc


# --------------------------------------------------------------------------- #
# Provider interface
# --------------------------------------------------------------------------- #
class Provider(abc.ABC):
    """A configured model endpoint. One :class:`Provider` instance per entry in
    ``llm.providers``."""

    def __init__(self, name: str, model: str, transport: Transport):
        self.name = name
        self.model = model
        self.transport = transport

    @abc.abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        ...

    def embed(self, texts: list[str]) -> EmbeddingResponse:
        raise LLMError(f"provider '{self.name}' does not support embeddings")

    @abc.abstractmethod
    def endpoint_hosts(self) -> set[str]:
        """Hosts this provider may contact — contributes to the air-gap allow-list."""
