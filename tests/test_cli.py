"""Tests for the CLI surface (B0 gate)."""

from __future__ import annotations

import json

from click.testing import CliRunner

from legacylens.cli import cli

CONFIG = """\
version: 1
project:
  name: demo
languages: [cobol]
llm:
  providers:
    - name: local
      type: local
      model: m
  routing:
    default: local
audit:
  log_path: .legacylens/audit.log
index:
  path: .legacylens/index.db
output:
  dir: out
"""


def test_help():
    res = CliRunner().invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "legacylens" in res.output
    for sub in ("init", "index", "analyze", "graph", "doc", "report"):
        assert sub in res.output


def test_version():
    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0
    assert "legacylens" in res.output


def test_init_creates_config():
    runner = CliRunner()
    with runner.isolated_filesystem():
        res = runner.invoke(cli, ["init"])
        assert res.exit_code == 0
        from pathlib import Path

        text = Path("audit.yaml").read_text(encoding="utf-8")
        assert "version: 1" in text
        assert "air_gapped: true" in text


def test_init_refuses_overwrite_without_force():
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(cli, ["init"]).exit_code == 0
        res = runner.invoke(cli, ["init"])
        assert res.exit_code != 0
        # --force overwrites
        assert runner.invoke(cli, ["init", "--force"]).exit_code == 0


def test_command_validates_config_and_writes_audit():
    runner = CliRunner()
    with runner.isolated_filesystem():
        from pathlib import Path

        Path("audit.yaml").write_text(CONFIG, encoding="utf-8")
        Path("src").mkdir()  # CONFIG has no explicit root; defaults to "."
        res = runner.invoke(cli, ["index"])
        assert res.exit_code == 0, res.output
        log_path = Path(".legacylens/audit.log")
        assert log_path.exists()
        entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        assert entry["event"] == "index"
        assert entry["project"] == "demo"


INDEX_CONFIG = """\
version: 1
project:
  name: demo
  root: ./src
languages: [cobol]
llm:
  providers:
    - name: local
      type: local
      model: m
  routing:
    default: local
"""


def test_index_command_end_to_end():
    runner = CliRunner()
    with runner.isolated_filesystem():
        from pathlib import Path

        Path("audit.yaml").write_text(INDEX_CONFIG, encoding="utf-8")
        Path("src").mkdir()
        Path("src/A.cbl").write_text("       PROGRAM-ID. A.\n", encoding="utf-8")
        Path("src/notes.txt").write_text("not source", encoding="utf-8")

        res = runner.invoke(cli, ["index"])
        assert res.exit_code == 0, res.output
        assert Path(".legacylens/index.db").exists()
        entry = [
            json.loads(line)
            for line in Path(".legacylens/audit.log").read_text(encoding="utf-8").splitlines()
        ][-1]
        assert entry["event"] == "index"
        assert entry["added"] == 1
        assert entry["skipped_unknown"] == 1


def test_missing_config_is_clean_error():
    # Exercised through main(), which maps LegacyLensError to its exit_code.
    from legacylens.cli import main

    runner = CliRunner()
    with runner.isolated_filesystem():
        assert main(["analyze"]) == 2  # ConfigError.exit_code
