"""Custom rule packs loaded from YAML.

Lets clients add pattern-based detection rules without writing Python:

    name: acme
    rules:
      - id: ACME-001
        title: Hard-coded internal hostname
        severity: medium          # info|low|medium|high|critical
        cwe: CWE-1051             # optional
        owasp: null               # optional
        languages: [cobol, jcl]   # omit = all languages
        pattern: "acme-corp\\.internal"   # regex, matched per code line
        rationale: "..."
        remediation: "..."
        confidence: 0.8           # optional (default 0.8)

Each rule scans code lines (comments skipped, string literals blanked like the
built-ins) and yields a finding per match. The pack is registered under ``name`` and
selected by listing that name in ``analysis.compliance.rule_packs``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from ..errors import ConfigError
from .model import Finding, Severity
from .rules import RuleContext, _code_lines

_VALID_SEVERITIES = {s.value for s in Severity}


def _make_rule(spec: dict, pack_name: str):
    try:
        rule_id = str(spec["id"])
        pattern = re.compile(spec["pattern"], re.I)
    except (KeyError, re.error) as exc:
        raise ConfigError(f"invalid rule in pack '{pack_name}': {exc}") from exc

    title = str(spec.get("title", rule_id))
    severity = str(spec.get("severity", "medium")).lower()
    if severity not in _VALID_SEVERITIES:
        raise ConfigError(f"rule {rule_id}: severity must be one of {sorted(_VALID_SEVERITIES)}")
    cwe = spec.get("cwe")
    owasp = spec.get("owasp")
    languages = {str(x).lower() for x in spec.get("languages", [])}
    rationale = str(spec.get("rationale", ""))
    remediation = str(spec.get("remediation", ""))
    confidence = float(spec.get("confidence", 0.8))

    def rule(ctx: RuleContext) -> Iterable[Finding]:
        if languages and ctx.language not in languages:
            return
        for idx, line in _code_lines(ctx):
            # Match the raw code line (comments already skipped) — custom packs often
            # target string-literal contents such as hostnames or dataset names.
            if pattern.search(line):
                yield Finding(
                    rule_id=rule_id,
                    title=title,
                    severity=severity,
                    cwe=str(cwe) if cwe else None,
                    owasp=str(owasp) if owasp else None,
                    rel_path=ctx.rel_path,
                    line=idx,
                    evidence=line.strip()[:200],
                    rationale=rationale,
                    remediation=remediation,
                    confidence=confidence,
                    source="rule",
                    requires_human_review=False,
                )

    rule.__name__ = f"custom_{pack_name}_{rule_id}"
    return rule


def load_rule_pack(path: str | Path) -> tuple[str, list]:
    """Load a YAML rule pack; return (pack_name, [rule_functions])."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"rule pack file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or "name" not in data or "rules" not in data:
        raise ConfigError(f"invalid rule pack (need 'name' and 'rules'): {p}")
    name = str(data["name"])
    rules = [_make_rule(spec, name) for spec in data["rules"]]
    return name, rules


def load_custom_packs(paths: list[str | Path]) -> dict[str, list]:
    """Load multiple pack files into a {name: [rules]} registry."""
    registry: dict[str, list] = {}
    for path in paths:
        name, rules = load_rule_pack(path)
        registry[name] = rules
    return registry
