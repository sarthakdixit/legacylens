"""Adapter for OpenAI-compatible chat APIs.

Covers both the ``openai_compatible`` and ``local`` provider types — local servers
(Ollama, vLLM, llama.cpp's server, LM Studio, etc.) expose the same
``/chat/completions`` and ``/embeddings`` shapes, so one adapter serves both. The
only practical difference is that local endpoints usually need no API key.
"""

from __future__ import annotations

import os

from ...errors import ConfigError
from ..airgap import host_of
from ..base import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    LLMError,
    Provider,
    Transport,
    Usage,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider(Provider):
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
        headers = {}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            **request.extra,
        }
        if request.stop:
            payload["stop"] = request.stop

        data = self.transport.post_json(
            f"{self.base_url}/chat/completions", self._headers(), payload
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected completion response from '{self.name}': {data}") from exc

        usage = None
        if isinstance(data.get("usage"), dict):
            u = data["usage"]
            usage = Usage(
                prompt_tokens=int(u.get("prompt_tokens", 0)),
                completion_tokens=int(u.get("completion_tokens", 0)),
            )
        return CompletionResponse(
            text=text,
            model=data.get("model", self.model),
            provider=self.name,
            usage=usage,
            raw=data,
        )

    def embed(self, texts: list[str]) -> EmbeddingResponse:
        payload = {"model": self.model, "input": texts}
        data = self.transport.post_json(
            f"{self.base_url}/embeddings", self._headers(), payload
        )
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise LLMError(f"unexpected embeddings response from '{self.name}': {data}") from exc
        return EmbeddingResponse(
            vectors=vectors, model=data.get("model", self.model), provider=self.name
        )

    def endpoint_hosts(self) -> set[str]:
        host = host_of(self.base_url)
        if not host:
            raise ConfigError(f"provider '{self.name}' has an invalid base_url: {self.base_url}")
        return {host}
