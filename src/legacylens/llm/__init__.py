"""Bring-your-own LLM gateway.

The gateway is the only component that talks to a model. Everything else in
legacylens asks the gateway to run a *task* (e.g. ``"security"``, ``"documentation"``,
``"parse_fallback"``); the gateway resolves that task to a configured provider via
routing, enforces the air-gap allow-list, serves cached results when possible, and
returns a normalized response.

Public surface:

* :class:`~legacylens.llm.base.Message`, :class:`~legacylens.llm.base.CompletionRequest`,
  :class:`~legacylens.llm.base.CompletionResponse`, :class:`~legacylens.llm.base.EmbeddingResponse`
* :func:`~legacylens.llm.gateway.build_gateway`
* :class:`~legacylens.llm.gateway.Gateway`
"""

from .base import CompletionRequest, CompletionResponse, EmbeddingResponse, Message, Usage
from .gateway import Gateway, build_gateway

__all__ = [
    "Message",
    "CompletionRequest",
    "CompletionResponse",
    "EmbeddingResponse",
    "Usage",
    "Gateway",
    "build_gateway",
]
