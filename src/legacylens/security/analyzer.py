"""Security analysis orchestrator.

Runs the deterministic rule packs over every in-scope artifact, then (optionally)
asks the LLM for additional advisory findings. Rule findings are authoritative; LLM
findings are always flagged ``requires_human_review=True``.
"""

from __future__ import annotations

import json

from ..logging_setup import get_logger
from ..parsing import CobolParser
from ..parsing.model import CobolProgram
from ..store import IndexStore
from .model import Finding, Severity
from .rules import RuleContext, run_rules

log = get_logger()

_VALID_SEVERITIES = {s.value for s in Severity}


class SecurityAnalyzer:
    def __init__(self, rule_packs: list[str], gateway=None, parser: CobolParser | None = None):
        self.rule_packs = rule_packs
        self.gateway = gateway
        self.parser = parser or CobolParser(gateway=gateway)

    def analyze_estate(self, store: IndexStore) -> list[Finding]:
        findings: list[Finding] = []
        for art in store.iter_artifacts():  # streamed: bounded memory on large estates
            if art.language not in ("cobol", "jcl"):
                continue
            try:
                text = _read(art.abs_path)
            except OSError as exc:
                log.warning("could not read %s: %s", art.rel_path, exc)
                continue

            program: CobolProgram | None = None
            if art.language == "cobol":
                program = self.parser.parse(text, source_path=art.abs_path, kind=art.kind).program

            ctx = RuleContext(
                rel_path=art.rel_path,
                language=art.language,
                lines=text.splitlines(),
                program=program,
            )
            findings.extend(run_rules(ctx, self.rule_packs))
            if self.gateway is not None:
                findings.extend(self._llm_findings(art.rel_path, art.language, text))

        findings.sort(key=lambda f: (-f.rank, f.rel_path, f.line))
        return findings

    # -- LLM advisory ------------------------------------------------------- #
    def _llm_findings(self, rel_path: str, language: str, text: str) -> list[Finding]:
        from ..llm import CompletionRequest, Message

        prompt = (
            f"You are a security auditor reviewing legacy {language.upper()} code. "
            "Identify security vulnerabilities NOT limited to simple patterns. "
            "Return ONLY a JSON array; each item: "
            '{"title": str, "severity": "info|low|medium|high|critical", '
            '"cwe": str|null, "owasp": str|null, "line": int, "rationale": str, '
            '"remediation": str, "confidence": number between 0 and 1}. '
            "Return [] if none.\n\nSOURCE:\n" + text[:6000]
        )
        try:
            resp = self.gateway.complete(
                "security", CompletionRequest(messages=[Message(role="user", content=prompt)])
            )
            items = _extract_json_array(resp.text)
        except Exception as exc:
            log.warning("LLM security analysis failed for %s: %s", rel_path, exc)
            return []

        out: list[Finding] = []
        for item in items:
            if not isinstance(item, dict) or "title" not in item:
                continue
            severity = str(item.get("severity", "medium")).lower()
            if severity not in _VALID_SEVERITIES:
                severity = Severity.medium.value
            out.append(
                Finding(
                    rule_id="LLM-ADVISORY",
                    title=str(item["title"])[:200],
                    severity=severity,
                    cwe=_str_or_none(item.get("cwe")),
                    owasp=_str_or_none(item.get("owasp")),
                    rel_path=rel_path,
                    line=int(item["line"]) if str(item.get("line", "")).isdigit() else 0,
                    evidence="(LLM-identified; verify against source)",
                    rationale=str(item.get("rationale", ""))[:1000],
                    remediation=str(item.get("remediation", ""))[:1000],
                    confidence=_clamp_confidence(item.get("confidence", 0.5)),
                    source="llm",
                    requires_human_review=True,
                )
            )
        return out


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _str_or_none(v) -> str | None:
    return str(v) if isinstance(v, str) and v.strip() else None


def _clamp_confidence(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, f))


def _extract_json_array(text: str) -> list:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array in response")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    return data
