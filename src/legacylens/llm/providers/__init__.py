"""Provider adapters and the factory that builds them from config."""

from __future__ import annotations

from ...config import ProviderConfig, ProviderType
from ..base import Provider, Transport
from .anthropic import AnthropicProvider
from .openai_compatible import OpenAICompatibleProvider

__all__ = ["build_provider", "OpenAICompatibleProvider", "AnthropicProvider"]


def build_provider(cfg: ProviderConfig, transport: Transport) -> Provider:
    """Instantiate the right provider adapter for a config entry."""
    if cfg.type in (ProviderType.openai_compatible, ProviderType.local):
        return OpenAICompatibleProvider(
            name=cfg.name,
            model=cfg.model,
            transport=transport,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
        )
    if cfg.type is ProviderType.anthropic:
        return AnthropicProvider(
            name=cfg.name,
            model=cfg.model,
            transport=transport,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
        )
    raise ValueError(f"unsupported provider type: {cfg.type}")  # pragma: no cover
