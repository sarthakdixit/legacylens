"""Adapter for the Anthropic Messages API.

Differences from the OpenAI-compatible shape that this adapter normalizes:

* The system prompt is a top-level ``system`` field, not a message with role
  ``system``; we split it out.
* Auth uses the ``x-api-key`` header plus an ``anthropic-version`` header.
* The response text lives in ``content[].text`` and usage in
  ``usage.input_tokens`` / ``usage.output_tokens``.
* There is no embeddings endpoint — :meth:`embed` raises.
"""

from __future__ import annotations

import os

from ...errors import ConfigError
from ..airgap import host_of
from ..base import (
    CompletionRequest,
    CompletionResponse,
    LLMError,
    Provider,
    Transport,
    Usage,
)

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    def __init__(
        self,
        name: str,
        model: str,
        transport: Transport,
        base_url: str | None,
        api_key_env: str | None,
    ):
        super().__init__(name=name, model=model, transport=transport)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key_env = api_key_env

    def _headers(self) -> dict[str, str]:
        headers = {"anthropic-version": ANTHROPIC_VERSION}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if key:
                headers["x-api-key"] = key
        return headers

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        turns = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role != "system"
        ]
        payload = {
            "model": self.model,
            "messages": turns,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            **request.extra,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.stop:
            payload["stop_sequences"] = request.stop

        data = self.transport.post_json(
            f"{self.base_url}/v1/messages", self._headers(), payload
        )
        try:
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise LLMError(f"unexpected completion response from '{self.name}': {data}") from exc

        usage = None
        if isinstance(data.get("usage"), dict):
            u = data["usage"]
            usage = Usage(
                prompt_tokens=int(u.get("input_tokens", 0)),
                completion_tokens=int(u.get("output_tokens", 0)),
            )
        return CompletionResponse(
            text=text,
            model=data.get("model", self.model),
            provider=self.name,
            usage=usage,
            raw=data,
        )

    def endpoint_hosts(self) -> set[str]:
        host = host_of(self.base_url)
        if not host:
            raise ConfigError(f"provider '{self.name}' has an invalid base_url: {self.base_url}")
        return {host}
