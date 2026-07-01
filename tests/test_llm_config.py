"""Tests for the simple llm_config.yaml (url/model/key) convenience file."""

from __future__ import annotations

import os
import textwrap

import pytest

from legacylens.config import load_config
from legacylens.errors import ConfigError

# An audit.yaml with NO `llm:` block — the LLM comes from llm_config.yaml.
AUDIT_NO_LLM = """\
version: 1
project:
  name: demo
languages: [cobol]
"""


def _write(dir_, name, text):
    p = dir_ / name
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_llm_config_autodetected_with_inline_key(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLENS_LLM_KEY", raising=False)
    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM)
    _write(
        tmp_path,
        "llm_config.yaml",
        """
        type: openai_compatible
        url: https://generativelanguage.googleapis.com/v1beta/openai
        model: gemini-2.0-flash
        key: SECRET-KEY-123
        """,
    )
    cfg = load_config(tmp_path / "audit.yaml")
    assert cfg.llm is not None
    p = cfg.llm.providers[0]
    assert p.type.value == "openai_compatible"
    assert p.model == "gemini-2.0-flash"
    assert p.base_url.startswith("https://generativelanguage")
    assert cfg.llm.routing.default == "default"
    # Inline key is injected into the environment (never stored on the provider).
    assert p.api_key_env == "LEGACYLENS_LLM_KEY"
    assert os.environ["LEGACYLENS_LLM_KEY"] == "SECRET-KEY-123"


def test_llm_config_with_api_key_env(tmp_path):
    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM)
    _write(
        tmp_path,
        "llm_config.yaml",
        """
        url: https://api.openai.com/v1
        model: gpt-4o-mini
        api_key_env: OPENAI_API_KEY
        embedding_model: text-embedding-3-small
        """,
    )
    cfg = load_config(tmp_path / "audit.yaml")
    assert cfg.llm.providers[0].api_key_env == "OPENAI_API_KEY"
    assert cfg.llm.embeddings.provider == "default"
    assert cfg.llm.embeddings.model == "text-embedding-3-small"


def test_explicit_llm_config_path(tmp_path):
    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM + "llm_config: my_llm.yaml\n")
    _write(tmp_path, "my_llm.yaml", "type: local\nurl: http://localhost:11434/v1\nmodel: qwen\n")
    cfg = load_config(tmp_path / "audit.yaml")
    assert cfg.llm.providers[0].type.value == "local"


def test_inline_llm_block_takes_precedence(tmp_path):
    # If audit.yaml has an `llm:` block, llm_config.yaml is ignored.
    _write(
        tmp_path,
        "audit.yaml",
        AUDIT_NO_LLM
        + "llm:\n  providers: [{name: p, type: local, model: m}]\n  routing: {default: p}\n",
    )
    _write(tmp_path, "llm_config.yaml", "model: should-be-ignored\n")
    cfg = load_config(tmp_path / "audit.yaml")
    assert cfg.llm.providers[0].name == "p"


def test_no_llm_and_no_llm_config_errors(tmp_path):
    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM)
    with pytest.raises(ConfigError, match="no LLM provider configured"):
        load_config(tmp_path / "audit.yaml")


def test_llm_config_missing_model_errors(tmp_path):
    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM)
    _write(tmp_path, "llm_config.yaml", "url: http://x/v1\n")
    with pytest.raises(ConfigError, match="'model' is required"):
        load_config(tmp_path / "audit.yaml")


def test_named_llm_config_not_found_errors(tmp_path):
    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM + "llm_config: nope.yaml\n")
    with pytest.raises(ConfigError, match="llm_config file not found"):
        load_config(tmp_path / "audit.yaml")


def test_example_llm_config_is_valid(tmp_path):
    # The shipped example must build a usable llm block.
    from pathlib import Path

    _write(tmp_path, "audit.yaml", AUDIT_NO_LLM + "llm_config: ex.yaml\n")
    example = Path(__file__).resolve().parents[1] / "examples" / "llm_config.example.yaml"
    (tmp_path / "ex.yaml").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = load_config(tmp_path / "audit.yaml")
    assert cfg.llm.providers[0].model == "gemini-2.0-flash"
