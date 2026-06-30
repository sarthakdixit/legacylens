"""Deterministic CWE/OWASP rule pack for legacy (COBOL/JCL) sources.

Each rule is a function over a :class:`RuleContext` yielding :class:`Finding`s. Rules
are pattern- or structure-based and fully reproducible, so their findings are
authoritative (``source="rule"``, ``requires_human_review=False``). The pack is keyed
by name (``"cwe"``/``"owasp"`` both map to this combined pack in v1); custom packs can
be registered later without touching callers.

Comment lines are skipped per language so commented-out code never produces a finding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ..parsing.model import CobolProgram
from .model import Finding, Severity

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_SECRET_KW = re.compile(r"(?i)\b(PASSWORD|PASSWD|PASS-WORD|PWD|SECRET|API-?KEY|PASSPHRASE)\b")
_JCL_PASSWORD = re.compile(r"(?i)\b(PASSWORD|PASS|PWD)\s*=\s*[^,\s]+")
_DYNAMIC_SQL = re.compile(r"(?i)\b(EXECUTE\s+IMMEDIATE|PREPARE)\b")
_SENSITIVE_FIELD = re.compile(r"(?i)\b[\w-]*(PASSWORD|PASSWD|PWD|SSN|SOC-SEC|CARD|PIN|ACCT-NO|ACCOUNT-NO)[\w-]*\b")
_DISPLAY = re.compile(r"(?i)\bDISPLAY\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@dataclass
class RuleContext:
    rel_path: str
    language: str
    lines: list[str]
    program: CobolProgram | None = None


def _code_lines(ctx: RuleContext) -> Iterator[tuple[int, str]]:
    """Yield (1-based line number, line) skipping comments for the language."""
    for idx, raw in enumerate(ctx.lines, start=1):
        line = raw.rstrip("\r\n")
        if ctx.language == "cobol":
            if len(line) >= 7 and line[6] in ("*", "/"):
                continue
        elif ctx.language == "jcl":
            if line.startswith("//*"):
                continue
        yield idx, line


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def rule_hardcoded_secret(ctx: RuleContext) -> Iterable[Finding]:
    if ctx.language != "cobol":
        return
    for idx, line in _code_lines(ctx):
        if _SECRET_KW.search(line) and _QUOTED.search(line):
            yield Finding(
                rule_id="LL-SEC-001",
                title="Hard-coded credential or secret",
                severity=Severity.high.value,
                cwe="CWE-798",
                owasp="A07:2021",
                rel_path=ctx.rel_path,
                line=idx,
                evidence=line.strip()[:200],
                rationale="A secret-bearing field is assigned a literal value in source.",
                remediation="Move secrets to an external secret store / parameter; never embed in source.",
                confidence=0.85,
                source="rule",
                requires_human_review=False,
            )


def rule_jcl_password(ctx: RuleContext) -> Iterable[Finding]:
    if ctx.language != "jcl":
        return
    for idx, line in _code_lines(ctx):
        if _JCL_PASSWORD.search(line):
            yield Finding(
                rule_id="LL-SEC-002",
                title="Hard-coded password in JCL",
                severity=Severity.high.value,
                cwe="CWE-798",
                owasp="A07:2021",
                rel_path=ctx.rel_path,
                line=idx,
                evidence=line.strip()[:200],
                rationale="A PASSWORD= parameter exposes credentials in cleartext JCL.",
                remediation="Use a security product (e.g. RACF) and remove embedded passwords.",
                confidence=0.9,
                source="rule",
                requires_human_review=False,
            )


def rule_dynamic_sql(ctx: RuleContext) -> Iterable[Finding]:
    if ctx.language != "cobol":
        return
    for idx, line in _code_lines(ctx):
        if _DYNAMIC_SQL.search(line):
            yield Finding(
                rule_id="LL-SEC-003",
                title="Possible SQL injection via dynamic SQL",
                severity=Severity.high.value,
                cwe="CWE-89",
                owasp="A03:2021",
                rel_path=ctx.rel_path,
                line=idx,
                evidence=line.strip()[:200],
                rationale="Dynamically built/executed SQL can be injectable if it incorporates untrusted input.",
                remediation="Use static SQL with host variables / parameter markers instead of dynamic statements.",
                confidence=0.6,
                source="rule",
                requires_human_review=False,
            )


def rule_sensitive_display(ctx: RuleContext) -> Iterable[Finding]:
    if ctx.language != "cobol":
        return
    for idx, line in _code_lines(ctx):
        if _DISPLAY.search(line) and _SENSITIVE_FIELD.search(line):
            yield Finding(
                rule_id="LL-SEC-004",
                title="Sensitive data written to log/output",
                severity=Severity.medium.value,
                cwe="CWE-532",
                owasp="A09:2021",
                rel_path=ctx.rel_path,
                line=idx,
                evidence=line.strip()[:200],
                rationale="A DISPLAY statement references a sensitive field, risking exposure in logs/SYSOUT.",
                remediation="Mask or remove sensitive values before DISPLAY; avoid logging secrets/PII.",
                confidence=0.7,
                source="rule",
                requires_human_review=False,
            )


def rule_dynamic_call(ctx: RuleContext) -> Iterable[Finding]:
    if ctx.program is None:
        return
    for call in ctx.program.calls:
        if call.dynamic:
            yield Finding(
                rule_id="LL-SEC-005",
                title="Dynamic program CALL",
                severity=Severity.medium.value,
                cwe="CWE-94",
                owasp="A03:2021",
                rel_path=ctx.rel_path,
                line=call.line,
                evidence=f"CALL {call.target} (target resolved at runtime)",
                rationale="A dynamically resolved CALL target can divert control flow if the variable is influenced by input.",
                remediation="Validate/whitelist the program name, or use static CALLs where possible.",
                confidence=0.6,
                source="rule",
                requires_human_review=False,
            )


def rule_hardcoded_ip(ctx: RuleContext) -> Iterable[Finding]:
    for idx, line in _code_lines(ctx):
        for m in _IPV4.finditer(line):
            octets = m.group(0).split(".")
            if all(0 <= int(o) <= 255 for o in octets):
                yield Finding(
                    rule_id="LL-SEC-006",
                    title="Hard-coded IP address",
                    severity=Severity.low.value,
                    cwe="CWE-1051",
                    owasp=None,
                    rel_path=ctx.rel_path,
                    line=idx,
                    evidence=line.strip()[:200],
                    rationale="A hard-coded network address reduces portability and can leak environment topology.",
                    remediation="Externalize endpoints into configuration.",
                    confidence=0.8,
                    source="rule",
                    requires_human_review=False,
                )
                break  # one finding per line is enough


# Rules grouped into the named pack(s). CWE and OWASP both resolve to this pack in v1.
_ALL_RULES = [
    rule_hardcoded_secret,
    rule_jcl_password,
    rule_dynamic_sql,
    rule_sensitive_display,
    rule_dynamic_call,
    rule_hardcoded_ip,
]

RULE_PACKS: dict[str, list] = {
    "cwe": _ALL_RULES,
    "owasp": _ALL_RULES,
}


def run_rules(ctx: RuleContext, packs: list[str]) -> list[Finding]:
    """Run the rules from the named packs against a context (deduped by rule)."""
    seen_funcs = []
    for pack in packs:
        for fn in RULE_PACKS.get(pack, []):
            if fn not in seen_funcs:
                seen_funcs.append(fn)
    findings: list[Finding] = []
    for fn in seen_funcs:
        findings.extend(fn(ctx))
    return findings
