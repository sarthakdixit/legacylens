"""Tests for the LLM gateway: adapters, routing, caching, air-gap (B1 gate)."""

from __future__ import annotations

import pytest

from legacylens.config import Config
from legacylens.errors import AirGapViolationError, ConfigError
from legacylens.llm import CompletionRequest, Message, build_gateway
from legacylens.llm.airgap import AirGapTransport


class FakeTransport:
    """In-memory transport. Echoes the requested model so routing is observable."""

    def __init__(self):
        self.calls = []

    def post_json(self, url, headers, payload, timeout=60.0):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        model = payload.get("model", "?")
        if url.endswith("/chat/completions"):
            return {
                "model": model,
                "choices": [{"message": {"content": f"reply from {model}"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5},
            }
        if url.endswith("/embeddings"):
            return {"model": model, "data": [{"embedding": [0.1, 0.2, 0.3]} for _ in payload["input"]]}
        if url.endswith("/v1/messages"):
            return {
                "model": model,
                "content": [{"type": "text", "text": f"claude reply from {model}"}],
                "usage": {"input_tokens": 7, "output_tokens": 9},
            }
        raise AssertionError(f"unexpected url {url}")


def make_config(**overrides) -> Config:
    base = {
        "version": 1,
        "project": {"name": "demo"},
        "languages": ["cobol"],
        "llm": {
            "providers": [
                {
                    "name": "local",
                    "type": "local",
                    "model": "local-model",
                    "base_url": "http://localhost:11434/v1",
                },
                {
                    "name": "claude",
                    "type": "anthropic",
                    "model": "claude-opus-4-8",
                    "base_url": "https://api.anthropic.com",
                    "api_key_env": "TEST_ANTHROPIC_KEY",
                },
            ],
            "routing": {"default": "local", "security": "claude"},
            "embeddings": {"provider": "local", "model": "embed-model"},
        },
    }
    base.update(overrides)
    return Config.model_validate(base)


def _req(text="hello"):
    return CompletionRequest(messages=[Message(role="user", content=text)])


def test_openai_compatible_completion():
    t = FakeTransport()
    gw = build_gateway(make_config(), transport=t, use_cache=False)
    resp = gw.complete("default", _req())
    assert resp.text == "reply from local-model"
    assert resp.provider == "local"
    assert resp.usage.total_tokens == 8
    assert t.calls[0]["url"].endswith("/chat/completions")


def test_anthropic_completion_and_system_split(monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "secret-key-123")
    t = FakeTransport()
    gw = build_gateway(make_config(), transport=t, use_cache=False)
    req = CompletionRequest(
        messages=[Message("system", "be precise"), Message("user", "hi")]
    )
    resp = gw.complete("security", req)
    assert resp.provider == "claude"
    assert "claude reply" in resp.text
    payload = t.calls[0]["payload"]
    assert payload["system"] == "be precise"  # system split out
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert t.calls[0]["headers"]["x-api-key"] == "secret-key-123"


def test_routing_selects_provider_per_task():
    t = FakeTransport()
    gw = build_gateway(make_config(), transport=t, use_cache=False)
    assert gw.complete("default", _req()).provider == "local"
    assert gw.complete("security", _req()).provider == "claude"
    # documentation has no explicit route -> falls back to default
    assert gw.complete("documentation", _req()).provider == "local"


def test_cache_hit_avoids_second_call(tmp_path):
    t = FakeTransport()
    cache_path = str(tmp_path / "cache.db")
    gw = build_gateway(make_config(), transport=t, cache_path=cache_path)
    first = gw.complete("default", _req("same"))
    second = gw.complete("default", _req("same"))
    assert first.cached is False
    assert second.cached is True
    assert second.text == first.text
    assert len(t.calls) == 1  # only one network call


def test_no_cache_when_temperature_nonzero(tmp_path):
    t = FakeTransport()
    gw = build_gateway(make_config(), transport=t, cache_path=str(tmp_path / "c.db"))
    req = CompletionRequest(messages=[Message("user", "x")], temperature=0.7)
    gw.complete("default", req)
    gw.complete("default", req)
    assert len(t.calls) == 2  # not cached


def test_embeddings():
    t = FakeTransport()
    gw = build_gateway(make_config(), transport=t, use_cache=False)
    resp = gw.embed(["a", "b"])
    assert len(resp.vectors) == 2
    assert resp.provider == "local"


def test_embeddings_requires_config():
    cfg = make_config()
    cfg.llm.embeddings = None
    gw = build_gateway(cfg, transport=FakeTransport(), use_cache=False)
    with pytest.raises(ConfigError, match="embeddings"):
        gw.embed(["a"])


def test_airgap_blocks_unlisted_host():
    guarded = AirGapTransport(FakeTransport(), allowed_hosts={"localhost:11434"})
    # allowed host passes through
    guarded.post_json("http://localhost:11434/v1/chat/completions", {}, {"model": "m", "input": []})
    # unlisted host is blocked
    with pytest.raises(AirGapViolationError, match="evil.example.com"):
        guarded.post_json("https://evil.example.com/v1/chat/completions", {}, {"model": "m"})


def test_airgap_enforced_through_gateway():
    # Anthropic provider points at api.anthropic.com, which is allow-listed because
    # it is a configured provider; a call to it must succeed under air-gap.
    t = FakeTransport()
    gw = build_gateway(make_config(air_gapped=True), transport=t, use_cache=False)
    assert gw.complete("security", _req()).provider == "claude"


def test_airgap_disabled_passes_transport_through():
    t = FakeTransport()
    gw = build_gateway(make_config(air_gapped=False), transport=t, use_cache=False)
    assert gw.complete("default", _req()).text == "reply from local-model"
