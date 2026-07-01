"""Tests for findings lifecycle: fingerprints, baseline, suppression, gating."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from legacylens.cli import main
from legacylens.security import Finding
from legacylens.security.state import (
    add_suppression,
    apply_suppressions,
    diff,
    load_baseline,
    load_suppressions,
    write_baseline,
)


def _finding(rule="LL-SEC-001", path="a.cbl", line=5, evidence="x", title="t", cwe="CWE-798"):
    return Finding(
        rule_id=rule, title=title, severity="high", rel_path=path, line=line,
        evidence=evidence, rationale="r", remediation="m", confidence=0.9,
        source="rule", requires_human_review=False, cwe=cwe,
    )


# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #
def test_fingerprint_is_line_independent():
    a = _finding(line=5)
    b = _finding(line=99)  # same everything but line
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_differs_by_rule_or_evidence():
    assert _finding(evidence="x").fingerprint() != _finding(evidence="y").fingerprint()
    assert _finding(rule="LL-SEC-001").fingerprint() != _finding(rule="LL-SEC-004").fingerprint()


# --------------------------------------------------------------------------- #
# Baseline & diff
# --------------------------------------------------------------------------- #
def test_baseline_write_load_and_diff(tmp_path):
    f1, f2 = _finding(evidence="one"), _finding(evidence="two")
    path = tmp_path / "baseline.json"
    assert write_baseline(path, [f1, f2]) == 2
    base = load_baseline(path)
    assert base == {f1.fingerprint(), f2.fingerprint()}

    # New run: f2 remains, f1 gone, f3 added.
    f3 = _finding(evidence="three")
    new, resolved = diff([f2, f3], base)
    assert [f.fingerprint() for f in new] == [f3.fingerprint()]
    assert resolved == [f1.fingerprint()]


def test_load_baseline_missing_returns_empty(tmp_path):
    assert load_baseline(tmp_path / "nope.json") == set()


# --------------------------------------------------------------------------- #
# Suppressions
# --------------------------------------------------------------------------- #
def test_suppression_add_and_apply(tmp_path):
    path = tmp_path / "suppressions.json"
    f = _finding()
    fp = f.fingerprint()
    assert add_suppression(path, fp, reason="false positive") is True
    assert add_suppression(path, fp) is False  # already present

    supp = load_suppressions(path)
    assert fp in supp and supp[fp] == "false positive"

    count = apply_suppressions([f], supp)
    assert count == 1 and f.suppressed is True


# --------------------------------------------------------------------------- #
# CLI gating + suppression end-to-end
# --------------------------------------------------------------------------- #
_CONFIG = """\
version: 1
project:
  name: gate-demo
  root: ./src
languages: [cobol]
llm:
  providers: [{name: local, type: local, model: m}]
  routing: {default: local}
"""

_PROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. A.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PASSWORD PIC X(8) VALUE 'S3CR3T!!'.
       PROCEDURE DIVISION.
       MAIN.
           DISPLAY 'HELLO'.
           GOBACK.
"""


def _setup(runner):
    Path("audit.yaml").write_text(_CONFIG, encoding="utf-8")
    Path("src").mkdir()
    Path("src/A.cbl").write_text(_PROG, encoding="utf-8")
    assert main(["index"]) == 0


def _stored_fingerprint() -> str:
    from legacylens.store import IndexStore

    store = IndexStore(".legacylens/index.db")
    fds = [Finding.from_dict(d) for d in store.list_findings()]
    store.close()
    highs = [f for f in fds if f.severity == "high"]
    assert highs, "expected a high finding"
    return highs[0].fingerprint()


def test_fail_on_gates_and_suppression_clears_it():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _setup(runner)
        # One high finding → gate fails with the dedicated exit code.
        assert main(["analyze", "--no-llm", "--fail-on", "high"]) == 6
        # Nothing at critical → gate passes.
        assert main(["analyze", "--no-llm", "--fail-on", "critical"]) == 0
        # Suppress the high finding, then the high gate passes.
        fp = _stored_fingerprint()
        assert main(["suppress", fp]) == 0
        assert main(["analyze", "--no-llm", "--fail-on", "high"]) == 0


def test_baseline_makes_findings_not_new():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _setup(runner)
        assert main(["analyze", "--no-llm"]) == 0
        assert main(["baseline"]) == 0
        # With everything baselined, --new-only gate passes even at high.
        assert main(["analyze", "--no-llm", "--fail-on", "high", "--new-only"]) == 0
        # But without --new-only it still gates on the existing high finding.
        assert main(["analyze", "--no-llm", "--fail-on", "high"]) == 6


def test_json_output_includes_fingerprint():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _setup(runner)
        main(["analyze", "--no-llm"])
        Path("audit.yaml").write_text(
            _CONFIG + "output:\n  formats: [json]\n  dir: out\n", encoding="utf-8"
        )
        assert main(["report"]) == 0
        data = json.loads(Path("out/findings.json").read_text(encoding="utf-8"))
        assert all("fingerprint" in f for f in data["findings"])
        assert "suppressed" in data["summary"]
