"""Tests for the dependency preflight and bootstrap entry point."""

from __future__ import annotations

import pytest

import legacylens._preflight as pf


def test_ensure_dependencies_noop_when_all_present():
    # In the test env everything is installed → returns without prompting/installing.
    assert pf.ensure_dependencies() is None


def test_ensure_dependencies_exits_when_missing_and_no_consent(monkeypatch):
    monkeypatch.setattr(pf, "REQUIRED", [("legacylens_absent_pkg", "legacylens-absent-pkg>=1")])
    monkeypatch.delenv("LEGACYLENS_AUTO_INSTALL", raising=False)
    # Non-interactive (pytest stdin isn't a tty) → no consent → clean exit, no install.
    with pytest.raises(SystemExit) as exc:
        pf.ensure_dependencies()
    assert exc.value.code == 1


def test_missing_detects_absent_package(monkeypatch):
    monkeypatch.setattr(pf, "REQUIRED", [("click", "click>=8.1"), ("nope_xyz", "nope-xyz")])
    missing = pf._missing()
    assert missing == [("nope_xyz", "nope-xyz")]


def test_bootstrap_runs_preflight_then_cli(monkeypatch):
    import legacylens.bootstrap as boot

    calls = {}

    def fake_preflight():
        calls["preflight"] = True

    def fake_cli(argv=None):
        calls["argv"] = argv
        return 0

    monkeypatch.setattr("legacylens._preflight.ensure_dependencies", fake_preflight)
    monkeypatch.setattr("legacylens.cli.main", fake_cli)

    rc = boot.main(["doctor"])
    assert rc == 0
    assert calls["preflight"] is True
    assert calls["argv"] == ["doctor"]
