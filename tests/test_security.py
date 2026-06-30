"""Tests for security & compliance analysis (B5 gate)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from legacylens.config import Config
from legacylens.llm import build_gateway
from legacylens.parsing import CobolParser
from legacylens.security import Finding, SecurityAnalyzer, to_html, to_json, to_sarif
from legacylens.security.rules import RuleContext, run_rules
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


def _ctx_for(rel: str, language: str):
    text = (FIXTURES / rel).read_text(encoding="utf-8")
    program = None
    if language == "cobol":
        program = CobolParser().parse(text, kind="program").program
    return RuleContext(rel_path=rel, language=language, lines=text.splitlines(), program=program)


# --------------------------------------------------------------------------- #
# Deterministic rules
# --------------------------------------------------------------------------- #
def test_rules_detect_cobol_vulnerabilities():
    findings = run_rules(_ctx_for("vuln/VULN.cbl", "cobol"), ["cwe", "owasp"])
    ids = {f.rule_id for f in findings}
    assert {"LL-SEC-001", "LL-SEC-003", "LL-SEC-004", "LL-SEC-005"} <= ids
    # All deterministic findings are authoritative.
    assert all(f.source == "rule" for f in findings)
    assert all(f.requires_human_review is False for f in findings)
    # Hardcoded secret appears on both the VALUE and the MOVE line.
    assert sum(1 for f in findings if f.rule_id == "LL-SEC-001") == 2


def test_rules_map_to_cwe_and_owasp():
    findings = run_rules(_ctx_for("vuln/VULN.cbl", "cobol"), ["cwe", "owasp"])
    secret = next(f for f in findings if f.rule_id == "LL-SEC-001")
    assert secret.cwe == "CWE-798"
    assert secret.owasp == "A07:2021"
    sqli = next(f for f in findings if f.rule_id == "LL-SEC-003")
    assert sqli.cwe == "CWE-89"


def test_jcl_password_rule():
    findings = run_rules(_ctx_for("vuln/VULNJOB.jcl", "jcl"), ["cwe"])
    pw = [f for f in findings if f.rule_id == "LL-SEC-002"]
    assert len(pw) == 1
    assert pw[0].cwe == "CWE-798"


def test_clean_program_has_no_secret_findings():
    findings = run_rules(_ctx_for("cobol/PAYROLL.cbl", "cobol"), ["cwe", "owasp"])
    assert not any(f.rule_id in {"LL-SEC-001", "LL-SEC-003"} for f in findings)


def test_comment_lines_do_not_trigger_rules():
    src = [
        "      * MOVE 'topsecret' TO WS-PASSWORD IS JUST A COMMENT",
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. C.",
    ]
    ctx = RuleContext(rel_path="c.cbl", language="cobol", lines=src, program=None)
    assert not run_rules(ctx, ["cwe"])


# --------------------------------------------------------------------------- #
# Analyzer over an indexed estate
# --------------------------------------------------------------------------- #
def _indexed_store(tmp_path) -> IndexStore:
    from legacylens.ingest import Indexer

    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES / "vuln", estate)
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol", "jcl"]).index(estate)
    return store


def test_analyzer_over_estate(tmp_path):
    store = _indexed_store(tmp_path)
    findings = SecurityAnalyzer(["cwe", "owasp"]).analyze_estate(store)
    store.close()
    ids = {f.rule_id for f in findings}
    assert {"LL-SEC-001", "LL-SEC-002", "LL-SEC-003", "LL-SEC-004", "LL-SEC-005"} <= ids
    # Sorted by severity descending (high first).
    ranks = [f.rank for f in findings]
    assert ranks == sorted(ranks, reverse=True)


def test_findings_persist_round_trip(tmp_path):
    store = _indexed_store(tmp_path)
    findings = SecurityAnalyzer(["cwe"]).analyze_estate(store)
    store.replace_findings([f.to_dict() for f in findings])
    reloaded = [Finding.from_dict(d) for d in store.list_findings()]
    store.close()
    assert len(reloaded) == len(findings)
    assert {f.rule_id for f in reloaded} == {f.rule_id for f in findings}


# --------------------------------------------------------------------------- #
# LLM advisory findings
# --------------------------------------------------------------------------- #
class FakeTransport:
    def post_json(self, url, headers, payload, timeout=60.0):
        content = (
            '[{"title": "Improper error handling", "severity": "medium", '
            '"cwe": "CWE-390", "owasp": "A04:2021", "line": 12, '
            '"rationale": "errors swallowed", "remediation": "handle them", "confidence": 0.7}]'
        )
        return {"choices": [{"message": {"content": content}}]}


def _gateway():
    cfg = Config.model_validate(
        {
            "version": 1,
            "project": {"name": "t"},
            "languages": ["cobol"],
            "llm": {
                "providers": [{"name": "local", "type": "local", "model": "m", "base_url": "http://localhost:1/v1"}],
                "routing": {"default": "local"},
            },
        }
    )
    return build_gateway(cfg, transport=FakeTransport(), use_cache=False)


def test_llm_findings_are_advisory(tmp_path):
    store = _indexed_store(tmp_path)
    analyzer = SecurityAnalyzer(["cwe"], gateway=_gateway())
    findings = analyzer.analyze_estate(store)
    store.close()
    llm = [f for f in findings if f.source == "llm"]
    assert llm  # at least one advisory finding produced
    assert all(f.requires_human_review for f in llm)
    assert all(f.rule_id == "LLM-ADVISORY" for f in llm)


# --------------------------------------------------------------------------- #
# Emitters
# --------------------------------------------------------------------------- #
def _sample_findings():
    return [
        Finding(
            rule_id="LL-SEC-001", title="Hard-coded credential", severity="high",
            rel_path="a.cbl", line=5, evidence="x", rationale="r", remediation="m",
            confidence=0.85, source="rule", requires_human_review=False,
            cwe="CWE-798", owasp="A07:2021",
        ),
        Finding(
            rule_id="LLM-ADVISORY", title="Advisory issue", severity="medium",
            rel_path="b.cbl", line=2, evidence="x", rationale="r", remediation="m",
            confidence=0.6, source="llm", requires_human_review=True,
            cwe="CWE-200", owasp=None,
        ),
    ]


def test_sarif_is_valid_and_maps_levels():
    sarif = json.loads(to_sarif(_sample_findings()))
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "legacylens"
    levels = {r["ruleId"]: r["level"] for r in run["results"]}
    assert levels["LL-SEC-001"] == "error"   # high -> error
    assert levels["LLM-ADVISORY"] == "warning"  # medium -> warning
    # advisory flag carried in properties
    adv = next(r for r in run["results"] if r["ruleId"] == "LLM-ADVISORY")
    assert adv["properties"]["requiresHumanReview"] is True


def test_json_emitter_has_summary():
    data = json.loads(to_json(_sample_findings()))
    assert data["summary"]["total"] == 2
    assert data["summary"]["requires_human_review"] == 1
    assert len(data["findings"]) == 2


def test_html_emitter_renders_findings():
    html = to_html(_sample_findings())
    assert "<table" in html
    assert "CWE-798" in html
    assert "Hard-coded credential" in html
    assert "review" in html  # advisory tag present
