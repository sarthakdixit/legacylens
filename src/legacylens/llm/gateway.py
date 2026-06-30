"""The LLM gateway: routing + air-gap + caching over configured providers.

Callers ask the gateway to run a *task* by name. The gateway:

1. resolves the task to a provider via ``llm.routing`` (with fallback to ``default``),
2. enforces the air-gap allow-list (built from all providers' endpoints),
3. returns a cached response when one exists (completions at temperature 0),
4. otherwise calls the provider, caches, and returns a normalized response.

``build_gateway`` wires everything from a validated :class:`~legacylens.config.Config`.
A ``transport`` may be injected (tests, or to swap the HTTP client); by default the
stdlib :class:`~legacylens.llm.base.UrllibTransport` is used.
"""

from __future__ import annotations

from dataclasses import asdict

from ..config import Config
from ..errors import ConfigError
from ..logging_setup import get_logger
from .airgap import AirGapTransport
from .budget import TokenBudget, estimate_tokens
from .base import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    Provider,
    Transport,
    UrllibTransport,
    Usage,
)
from .cache import LLMCache, NullCache, make_key
from .providers import build_provider

log = get_logger()


class Gateway:
    def __init__(
        self,
        providers: dict[str, Provider],
        routing: dict[str, str],
        cache,
        embeddings_provider: str | None = None,
        budget: TokenBudget | None = None,
    ):
        self._providers = providers
        self._routing = routing
        self._cache = cache
        self._embeddings_provider = embeddings_provider
        self.budget = budget or TokenBudget(None)

    @property
    def tokens_spent(self) -> int:
        return self.budget.spent

    # -- task resolution ---------------------------------------------------- #
    def provider_for(self, task: str) -> Provider:
        """Resolve a task name to a provider, falling back to ``default``."""
        name = self._routing.get(task, self._routing["default"])
        provider = self._providers.get(name)
        if provider is None:  # pragma: no cover - guarded at config load
            raise ConfigError(f"routing resolved task '{task}' to unknown provider '{name}'")
        return provider

    # -- completions -------------------------------------------------------- #
    def complete(self, task: str, request: CompletionRequest) -> CompletionResponse:
        provider = self.provider_for(task)
        cacheable = request.temperature == 0.0
        key = None
        if cacheable:
            key = make_key(provider.name, provider.model, "complete", request.cache_signature())
            hit = self._cache.get(key)
            if hit is not None:
                log.debug("LLM cache hit (task=%s, provider=%s)", task, provider.name)
                usage = Usage(**hit["usage"]) if hit.get("usage") else None
                return CompletionResponse(
                    text=hit["text"],
                    model=hit["model"],
                    provider=hit["provider"],
                    usage=usage,
                    cached=True,
                    raw=hit.get("raw", {}),
                )

        # Budget guard: estimate the prompt cost and refuse if it would overrun.
        estimated = sum(estimate_tokens(m.content) for m in request.messages) + request.max_tokens
        self.budget.check(estimated)

        log.debug("LLM call (task=%s, provider=%s, model=%s)", task, provider.name, provider.model)
        response = provider.complete(request)

        # Record actual usage when reported, else fall back to the estimate.
        spent = response.usage.total_tokens if response.usage else estimated
        self.budget.record(spent)

        if cacheable and key is not None:
            self._cache.set(
                key,
                {
                    "text": response.text,
                    "model": response.model,
                    "provider": response.provider,
                    "usage": asdict(response.usage) if response.usage else None,
                    "raw": response.raw,
                },
            )
        return response

    # -- embeddings --------------------------------------------------------- #
    def embed(self, texts: list[str]) -> EmbeddingResponse:
        if not self._embeddings_provider:
            raise ConfigError("no embeddings provider configured (set llm.embeddings)")
        provider = self._providers[self._embeddings_provider]
        return provider.embed(texts)

    def close(self) -> None:
        self._cache.close()


def build_gateway(
    config: Config,
    transport: Transport | None = None,
    cache_path: str | None = None,
    use_cache: bool = True,
) -> Gateway:
    """Construct a :class:`Gateway` from a validated config.

    The air-gap allow-list is computed from every provider's endpoint(s) and, when
    ``config.air_gapped`` is true, the transport is wrapped so nothing outside that
    list can be reached.
    """
    base_transport: Transport = transport or UrllibTransport()

    # Build providers once with the raw transport so we can read their endpoints.
    providers: dict[str, Provider] = {
        p.name: build_provider(p, base_transport) for p in config.llm.providers
    }

    if config.air_gapped:
        allowed: set[str] = set()
        for provider in providers.values():
            allowed |= provider.endpoint_hosts()
        guarded = AirGapTransport(base_transport, allowed)
        # Re-bind providers to the guarded transport.
        for provider in providers.values():
            provider.transport = guarded
        log.debug("Air-gap enforced; allowed hosts: %s", ", ".join(sorted(allowed)))

    if use_cache:
        path = cache_path or str(config.index.path.parent / "llm_cache.db")
        cache = LLMCache(path)
    else:
        cache = NullCache()

    embeddings_provider = config.llm.embeddings.provider if config.llm.embeddings else None

    return Gateway(
        providers=providers,
        routing=config.llm.routing.resolved(),
        cache=cache,
        embeddings_provider=embeddings_provider,
        budget=TokenBudget(config.budget.max_tokens),
    )
