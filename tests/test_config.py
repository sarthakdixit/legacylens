"""Tests for the config schema and loader (B0 gate)."""

from __future__ import annotations

import textwrap

import pytest

from legacylens.config import Config, OutputFormat, load_config
from legacylens.errors import ConfigError

VALID = """\
version: 1
project:
  name: demo
  root: ./src
languages:
  - cobol
  - jcl
llm:
  providers:
    - name: local
      type: local
      base_url: http://localhost:11434/v1
      model: qwen2.5-coder
  routing:
    default: local
analysis:
  compliance:
    rule_packs: [cwe, owasp]
output:
  formats: [sarif, markdown]
"""


def _write(tmp_path, text):
    p = tmp_path / "audit.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_loads_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert isinstance(cfg, Config)
    assert cfg.project.name == "demo"
    assert [lang.value for lang in cfg.languages] == ["cobol", "jcl"]
    assert OutputFormat.sarif in cfg.output.formats
    assert cfg.air_gapped is True  # defaults on


def test_routing_falls_back_to_default(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    resolved = cfg.llm.routing.resolved()
    assert resolved["security"] == "local"
    assert resolved["documentation"] == "local"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_empty_file_raises(tmp_path):
    p = tmp_path / "audit.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_config(p)


def test_unsupported_version_raises(tmp_path):
    with pytest.raises(ConfigError, match="version"):
        load_config(_write(tmp_path, VALID.replace("version: 1", "version: 2")))


def test_unknown_routing_provider_raises(tmp_path):
    bad = VALID.replace("default: local", "default: ghost")
    with pytest.raises(ConfigError, match="unknown provider 'ghost'"):
        load_config(_write(tmp_path, bad))


def test_duplicate_provider_name_raises(tmp_path):
    bad = VALID.replace(
        "  routing:",
        "    - name: local\n      type: local\n      model: m2\n  routing:",
    )
    with pytest.raises(ConfigError, match="duplicate provider"):
        load_config(_write(tmp_path, bad))


def test_unknown_key_rejected(tmp_path):
    bad = VALID + "bogus_key: true\n"
    with pytest.raises(ConfigError, match="bogus_key"):
        load_config(_write(tmp_path, bad))


def test_no_languages_rejected(tmp_path):
    bad = VALID.replace("languages:\n  - cobol\n  - jcl\n", "languages: []\n")
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_example_config_is_valid():
    # The shipped reference config must always load against the current schema.
    from pathlib import Path

    from legacylens.config import Config

    example = Path(__file__).resolve().parents[1] / "examples" / "audit.example.yaml"
    cfg = load_config(example)
    assert isinstance(cfg, Config)
    assert cfg.llm.routing.default in cfg.llm.provider_names()
