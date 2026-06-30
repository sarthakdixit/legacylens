"""Tests for documentation generation (B6 gate)."""

from __future__ import annotations

import shutil
from pathlib import Path

from legacylens.config import Config
from legacylens.docs import DocGenerator
from legacylens.graph import build_graph
from legacylens.ingest import Indexer
from legacylens.llm import build_gateway
from legacylens.parsing import CobolParser
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


def _estate(tmp_path, sub="cobol"):
    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES, estate)
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol", "jcl"]).index(estate)
    return store


def test_program_doc_deterministic(tmp_path):
    store = _estate(tmp_path)
    graph = build_graph(store)
    payroll = next(a for a in store.list_artifacts("cobol") if a.rel_path.endswith("PAYROLL.cbl"))
    # Parse with the absolute path as source_path to guard against it leaking into docs.
    prog = CobolParser().parse(
        Path(payroll.abs_path).read_text(), source_path=payroll.abs_path, kind="program"
    ).program
    store.close()

    md = DocGenerator().program_doc(prog, graph, payroll.rel_path, confidence=0.95)
    assert "# Program: PAYROLL" in md
    assert "## Purpose" in md
    assert "## Dependencies" in md
    assert "COPY → `EMPREC`" in md
    assert "CALL → `TAXCALC`" in md
    # Citations must be relative — no absolute/local paths leak into audit docs.
    assert payroll.abs_path not in md
    assert "Invoked by job(s):** RUNPAY" in md
    assert "`MAIN-PARA`" in md
    assert "WS-TOTAL" in md
    # citation format present
    assert "PAYROLL.cbl:" in md
    # no LLM → no review note
    assert "must be" not in md


def test_program_doc_with_llm_flags_inferred(tmp_path):
    store = _estate(tmp_path)
    graph = build_graph(store)
    payroll = next(a for a in store.list_artifacts("cobol") if a.rel_path.endswith("PAYROLL.cbl"))
    prog = CobolParser().parse(Path(payroll.abs_path).read_text(), kind="program").program
    store.close()

    class FakeTransport:
        def post_json(self, url, headers, payload, timeout=60.0):
            content = '{"purpose": "Computes payroll totals.", "business_logic": ["init", "call tax", "write"]}'
            return {"choices": [{"message": {"content": content}}]}

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
    gw = build_gateway(cfg, transport=FakeTransport(), use_cache=False)
    md = DocGenerator(gateway=gw).program_doc(prog, graph, payroll.rel_path, confidence=0.95)
    assert "Computes payroll totals." in md
    assert "_(inferred)_" in md
    assert "confirmed by a human" in md  # review note present


def test_overview_embeds_mermaid_and_summary(tmp_path):
    store = _estate(tmp_path)
    graph = build_graph(store)
    store.close()
    summary = {"total": 3, "by_severity": {"high": 2, "medium": 1}, "requires_human_review": 0}
    md = DocGenerator().overview(
        "demo", graph, [("PAYROLL", "program", "PAYROLL.md")], summary
    )
    assert "# System Documentation: demo" in md
    assert "```mermaid" in md
    assert "## Security summary" in md
    assert "Total findings:** 3" in md
    assert "[PAYROLL.md](PAYROLL.md)" in md
    assert "## Structural observations" in md
