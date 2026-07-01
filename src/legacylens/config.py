"""Configuration model and loader for legacylens.

The project config (``audit.yaml`` by convention) is the single source of truth for
a run: which languages to analyze, how the bring-your-own LLM providers are wired,
which compliance rule packs are active, and which output formats to emit.

The schema is defined with pydantic so that malformed config fails fast with a
precise, user-readable error rather than blowing up deep inside the pipeline.
"""

from __future__ import annotations

import enum
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import ConfigError

CONFIG_VERSION = 1
DEFAULT_CONFIG_NAME = "audit.yaml"
# Simple, single-model LLM file (url/model/key) — the easy alternative to a full
# `llm:` block. Auto-detected next to audit.yaml when no `llm:` block is present.
DEFAULT_LLM_CONFIG_NAME = "llm_config.yaml"
# Env var an inline `key:` from llm_config.yaml is injected into at load time, so the
# provider still reads credentials from the environment (never from a stored field).
_INJECTED_KEY_ENV = "LEGACYLENS_LLM_KEY"


class Language(str, enum.Enum):
    """Source languages legacylens can be asked to analyze."""

    cobol = "cobol"
    jcl = "jcl"
    pli = "pli"


class ProviderType(str, enum.Enum):
    """Supported bring-your-own LLM provider shapes."""

    openai_compatible = "openai_compatible"
    anthropic = "anthropic"
    local = "local"  # local HTTP server (Ollama / vLLM / llama.cpp), OpenAI-ish


class OutputFormat(str, enum.Enum):
    """Pluggable output emitters available to a run."""

    sarif = "sarif"
    json = "json"
    html = "html"
    markdown = "markdown"
    mermaid = "mermaid"
    dot = "dot"
    graphml = "graphml"


class StrictModel(BaseModel):
    """Base model that rejects unknown keys, so typos in config are caught early."""

    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictModel):
    name: str = Field(min_length=1)
    root: Path = Field(default=Path("."))


class ProviderConfig(StrictModel):
    name: str = Field(min_length=1)
    type: ProviderType
    model: str = Field(min_length=1)
    base_url: str | None = None
    # Credentials are never stored in config; we only name the env var to read.
    api_key_env: str | None = None


class RoutingConfig(StrictModel):
    """Maps pipeline tasks to a configured provider name.

    ``default`` is required; the others fall back to it when unset. Validation that
    each referenced provider actually exists happens in ``LLMConfig``.
    """

    default: str = Field(min_length=1)
    parse_fallback: str | None = None
    security: str | None = None
    documentation: str | None = None

    def resolved(self) -> dict[str, str]:
        """Return the effective task->provider map with fallbacks applied."""
        return {
            "default": self.default,
            "parse_fallback": self.parse_fallback or self.default,
            "security": self.security or self.default,
            "documentation": self.documentation or self.default,
        }


class EmbeddingsConfig(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class LLMConfig(StrictModel):
    providers: list[ProviderConfig] = Field(min_length=1)
    routing: RoutingConfig
    embeddings: EmbeddingsConfig | None = None

    @field_validator("providers")
    @classmethod
    def _unique_provider_names(cls, providers: list[ProviderConfig]) -> list[ProviderConfig]:
        names = [p.name for p in providers]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate provider name(s): {', '.join(sorted(dupes))}")
        return providers

    def provider_names(self) -> set[str]:
        return {p.name for p in self.providers}


class ComplianceConfig(StrictModel):
    # Packs to run: built-in "cwe"/"owasp" plus any custom pack names loaded from
    # pack_paths (a pack's YAML `name` makes it selectable here).
    rule_packs: list[str] = Field(default_factory=lambda: ["cwe", "owasp"])
    # Custom rule-pack YAML files (client-defined detection rules).
    pack_paths: list[Path] = Field(default_factory=list)
    # Regulatory frameworks to map findings to: built-in "pci-dss", "nist-800-53",
    # plus any loaded from framework_paths.
    frameworks: list[str] = Field(default_factory=list)
    # Custom framework mapping YAML files.
    framework_paths: list[Path] = Field(default_factory=list)


class ParserBackend(str, enum.Enum):
    """Which COBOL parsing backend to use."""

    regex = "regex"  # pure-Python, zero-dependency (default)
    antlr = "antlr"  # ANTLR grammar-based (higher fidelity; requires a build step)


class ParserConfig(StrictModel):
    backend: ParserBackend = ParserBackend.regex
    # If the selected backend is unavailable (e.g. the ANTLR parser has not been
    # generated), fall back to the regex parser instead of failing.
    fallback_to_regex: bool = True
    # Cache parse results in the index (content-addressed) for incremental reuse.
    cache: bool = True
    # Worker processes for parallel parse pre-warming (1 = serial). The CLI -j
    # flag overrides this.
    workers: int = Field(default=1, ge=1)


class AnalysisConfig(StrictModel):
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)


class IndexConfig(StrictModel):
    path: Path = Field(default=Path(".legacylens/index.db"))


class OutputConfig(StrictModel):
    formats: list[OutputFormat] = Field(default_factory=lambda: [OutputFormat.sarif, OutputFormat.markdown])
    dir: Path = Field(default=Path("legacylens-out"))


_SEVERITY_NAMES = {"info", "low", "medium", "high", "critical"}


class FindingsConfig(StrictModel):
    baseline_path: Path = Field(default=Path(".legacylens/baseline.json"))
    suppressions_path: Path = Field(default=Path(".legacylens/suppressions.json"))
    # Default CI gate: fail the run if any non-suppressed finding is at/above this
    # severity. None = never gate. The CLI --fail-on flag overrides this.
    fail_on: str | None = None

    @field_validator("fail_on")
    @classmethod
    def _valid_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in _SEVERITY_NAMES:
            raise ValueError(f"fail_on must be one of {sorted(_SEVERITY_NAMES)}, got '{v}'")
        return v


class AuditConfig(StrictModel):
    log_path: Path = Field(default=Path(".legacylens/audit.log"))


class BudgetConfig(StrictModel):
    # Hard ceiling on total LLM tokens (prompt + completion) for a run.
    # None = unlimited. Enforced by the gateway across all tasks.
    max_tokens: int | None = Field(default=None, ge=0)


class Config(StrictModel):
    """Top-level legacylens project configuration."""

    version: int = CONFIG_VERSION
    project: ProjectConfig
    languages: list[Language] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)
    # Either an inline `llm:` block, or `llm_config:` pointing at a simple
    # url/model/key file (auto-detected as llm_config.yaml when both are omitted).
    llm: LLMConfig | None = None
    llm_config: Path | None = None
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    findings: FindingsConfig = Field(default_factory=FindingsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    # When true, the LLM gateway (B1) must refuse any endpoint not explicitly
    # listed in the provider config. Defaults on: this is an air-gapped tool.
    air_gapped: bool = True

    @field_validator("version")
    @classmethod
    def _supported_version(cls, v: int) -> int:
        if v != CONFIG_VERSION:
            raise ValueError(
                f"unsupported config version {v}; this build supports version {CONFIG_VERSION}"
            )
        return v

    def validate_cross_references(self) -> None:
        """Validate references that span sections (e.g. routing -> provider names)."""
        if self.llm is None:
            return
        known = self.llm.provider_names()
        for task, provider in self.llm.routing.resolved().items():
            if provider not in known:
                raise ConfigError(
                    f"routing.{task} references unknown provider '{provider}'. "
                    f"Known providers: {', '.join(sorted(known)) or '(none)'}"
                )
        if self.llm.embeddings and self.llm.embeddings.provider not in known:
            raise ConfigError(
                f"llm.embeddings.provider references unknown provider "
                f"'{self.llm.embeddings.provider}'. "
                f"Known providers: {', '.join(sorted(known)) or '(none)'}"
            )


def load_config(path: str | Path) -> Config:
    """Load and fully validate a config file.

    Raises ``ConfigError`` with a readable message on any problem (missing file,
    invalid YAML, schema violation, or bad cross-reference).
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"config file not found: {path}. Run `legacylens init` to create one."
        )
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message passthrough
        raise ConfigError(f"could not parse YAML in {path}: {exc}") from exc

    if raw is None:
        raise ConfigError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}: {path}")

    # If there's no inline `llm:` block, build one from a simple llm_config file.
    if "llm" not in raw:
        _resolve_llm_config(raw, base_dir=path.parent)

    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc

    if config.llm is None:
        raise ConfigError(
            "no LLM provider configured — add an `llm:` block, or create "
            f"`{DEFAULT_LLM_CONFIG_NAME}` (url/model/key) next to {path.name} "
            "(see examples/llm_config.example.yaml)."
        )

    config.validate_cross_references()
    return config


def _resolve_llm_config(raw: dict, base_dir: Path) -> None:
    """Populate ``raw['llm']`` from a simple llm_config file when present.

    Path resolution: explicit ``llm_config:`` in the config, else a default
    ``llm_config.yaml`` next to the main config. No-op if neither exists (the
    missing-``llm`` error is raised later with guidance)."""
    ref = raw.get("llm_config")
    if ref:
        llm_path = Path(ref)
        if not llm_path.is_absolute():
            llm_path = base_dir / llm_path
        if not llm_path.exists():
            raise ConfigError(f"llm_config file not found: {llm_path}")
    else:
        llm_path = base_dir / DEFAULT_LLM_CONFIG_NAME
        if not llm_path.exists():
            return

    try:
        simple = yaml.safe_load(llm_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message passthrough
        raise ConfigError(f"could not parse {llm_path}: {exc}") from exc
    if not isinstance(simple, dict):
        raise ConfigError(f"{llm_path} must be a mapping with url/model/key.")

    model = simple.get("model")
    if not model:
        raise ConfigError(f"{llm_path}: 'model' is required.")

    provider: dict[str, Any] = {
        "name": "default",
        "type": simple.get("type", "openai_compatible"),
        "model": model,
    }
    if simple.get("url"):
        provider["base_url"] = simple["url"]

    # Inline `key:` is injected into the environment so the provider still reads it
    # from an env var; `api_key_env:` names an existing env var directly.
    if simple.get("key"):
        os.environ[_INJECTED_KEY_ENV] = str(simple["key"])
        provider["api_key_env"] = _INJECTED_KEY_ENV
    elif simple.get("api_key_env"):
        provider["api_key_env"] = simple["api_key_env"]

    llm: dict[str, Any] = {"providers": [provider], "routing": {"default": "default"}}
    if simple.get("embedding_model"):
        llm["embeddings"] = {"provider": "default", "model": simple["embedding_model"]}
    raw["llm"] = llm


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"invalid configuration in {path}:"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
