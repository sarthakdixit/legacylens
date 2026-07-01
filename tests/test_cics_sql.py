"""Tests for EXEC CICS / EXEC SQL parsing and graph edges."""

from __future__ import annotations

import shutil
from pathlib import Path

from legacylens.graph import EdgeType, NodeType, build_graph
from legacylens.ingest import Indexer
from legacylens.parsing import CobolParser
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


def _parse():
    return CobolParser().parse((FIXTURES / "cics" / "ACCTVIEW.cbl").read_text(), kind="program").program


def test_cics_link_is_a_static_call():
    prog = _parse()
    link = next(c for c in prog.calls if c.target == "INQCUST")
    assert link.mechanism == "CICS-LINK"
    assert link.dynamic is False


def test_cics_xctl_with_variable_is_dynamic():
    prog = _parse()
    xctl = next(c for c in prog.calls if c.target == "WS-PGM-NAME")
    assert xctl.mechanism == "CICS-XCTL"
    assert xctl.dynamic is True


def test_sql_tables_extracted():
    prog = _parse()
    tables = {(t.name, t.op) for t in prog.sql_tables}
    assert ("ACCTDB.ACCOUNTS", "SELECT") in tables
    assert ("ACCTDB.ACCOUNTS", "UPDATE") in tables
    # host variables (:WS-BAL) must not be captured as tables
    assert not any(t.name.startswith(":") for t in prog.sql_tables)


def test_exec_block_does_not_leak_paragraphs():
    prog = _parse()
    # END-EXEC. / SELECT lines etc. must not be mistaken for paragraphs.
    assert {p.name for p in prog.paragraphs} == {"MAIN-PARA"}


def test_graph_has_cics_and_sql_edges(tmp_path):
    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES / "cics", estate)
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol"]).index(estate)
    g = build_graph(store)
    store.close()

    edges = {(e.src, e.dst, e.type) for e in g.edges}
    assert ("ACCTVIEW", "INQCUST", EdgeType.cics) in edges
    assert ("ACCTVIEW", "WS-PGM-NAME", EdgeType.cics) in edges
    assert ("ACCTVIEW", "table:ACCTDB.ACCOUNTS", EdgeType.sql) in edges
    assert g.nodes["table:ACCTDB.ACCOUNTS"].type is NodeType.table
    assert g.nodes["table:ACCTDB.ACCOUNTS"].name == "ACCTDB.ACCOUNTS"
    # INQCUST is LINKed, so a program with that source would not be an orphan;
    # here it is unresolved (no source in this fixture).
    assert "INQCUST" in g.unresolved_references()


def test_cics_link_target_counts_against_orphans(tmp_path):
    # A CICS-linked program must not be reported as an orphan.
    estate = tmp_path / "estate"
    estate.mkdir()
    (estate / "A.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. A.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           EXEC CICS LINK PROGRAM('B') END-EXEC.\n"
        "           GOBACK.\n",
        encoding="utf-8",
    )
    (estate / "B.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. B.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           GOBACK.\n",
        encoding="utf-8",
    )
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol"]).index(estate)
    g = build_graph(store)
    store.close()
    assert "B" not in g.orphans()  # B is reached via CICS LINK
