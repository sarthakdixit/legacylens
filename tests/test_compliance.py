"""Tests for custom rule packs and regulatory compliance frameworks."""

from __future__ import annotations

from pathlib import Path

import pytest

from legacylens.errors import ConfigError
from legacylens.security import Finding
from legacylens.security.compliance import apply_frameworks, resolve_frameworks
from legacylens.security.packs import load_custom_packs, load_rule_pack
from legacylens.security.rules import RuleContext, run_rules

FIXTURES = Path(__file__).parent / "fixtures"


def _finding(cwe):
    return Finding(
        rule_id="R", title="t", severity="high", rel_path="a.cbl", line=1,
        evidence="x", rationale="", remediation="", confidence=0.9,
        source="rule", requires_human_review=False, cwe=cwe,
    )


# --------------------------------------------------------------------------- #
# Regulatory frameworks
# --------------------------------------------------------------------------- #
def test_builtin_frameworks_map_cwe_to_controls():
    fws = resolve_frameworks(["pci-dss", "nist-800-53"], [])
    findings = [_finding("CWE-798"), _finding("CWE-89")]
    apply_frameworks(findings, fws)
    assert "PCI-DSS:8.6.2" in findings[0].controls
    assert "NIST-800-53:IA-5" in findings[0].controls
    assert any(c.startswith("PCI-DSS:") for c in findings[1].controls)


def test_unknown_framework_raises():
    with pytest.raises(ConfigError, match="unknown framework"):
        resolve_frameworks(["gdpr-typo"], [])


def test_custom_framework_from_file():
    fws = resolve_frameworks([], [FIXTURES / "packs" / "acme-policy.yaml"])
    findings = [_finding("CWE-798")]
    apply_frameworks(findings, fws)
    assert "ACME-POLICY:SEC-1.1" in findings[0].controls
    assert "ACME-POLICY:SEC-1.2" in findings[0].controls


def test_finding_without_cwe_gets_no_controls():
    fws = resolve_frameworks(["pci-dss"], [])
    f = _finding(None)
    apply_frameworks([f], fws)
    assert f.controls == []


# --------------------------------------------------------------------------- #
# Custom rule packs
# --------------------------------------------------------------------------- #
def test_load_custom_pack_and_run():
    name, rules = load_rule_pack(FIXTURES / "packs" / "acme.yaml")
    assert name == "acme"
    ctx = RuleContext(
        rel_path="x.cbl",
        language="cobol",
        lines=["       MOVE 'host.acme-corp.internal' TO WS-HOST."],
        program=None,
    )
    registry = {"acme": rules}
    findings = run_rules(ctx, ["acme"], registry=registry)
    assert len(findings) == 1
    assert findings[0].rule_id == "ACME-001"
    assert findings[0].cwe == "CWE-1051"


def test_custom_pack_respects_language_filter():
    _, rules = load_rule_pack(FIXTURES / "packs" / "acme.yaml")
    # Pack targets [cobol, jcl]; a PL/I context should not match.
    ctx = RuleContext(
        rel_path="x.pli", language="pli", lines=["acme-corp.internal"], program=None
    )
    assert run_rules(ctx, ["acme"], registry={"acme": rules}) == []


def test_custom_pack_keyword_in_literal_still_matches_but_comment_skipped():
    # ACME pattern is not secret-like; ensure comment lines are skipped.
    _, rules = load_rule_pack(FIXTURES / "packs" / "acme.yaml")
    ctx = RuleContext(
        rel_path="x.cbl",
        language="cobol",
        lines=["      * acme-corp.internal in a comment", "       DISPLAY WS-X."],
        program=None,
    )
    assert run_rules(ctx, ["acme"], registry={"acme": rules}) == []


def test_invalid_pack_raises():
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write("name: bad\n")  # missing 'rules'
        path = fh.name
    with pytest.raises(ConfigError, match="invalid rule pack"):
        load_custom_packs([path])
