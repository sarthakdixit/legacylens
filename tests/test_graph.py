"""Tests for the dependency graph: model analyses, emitters, builder (B4 gate)."""

from __future__ import annotations

import shutil
import xml.dom.minidom
from pathlib import Path

from legacylens.graph import (
    DependencyGraph,
    EdgeType,
    NodeType,
    build_graph,
    to_dot,
    to_graphml,
    to_mermaid,
)
from legacylens.graph.jcl_links import extract_jcl_links
from legacylens.ingest import Indexer
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# Model analyses (synthetic graphs)
# --------------------------------------------------------------------------- #
def test_cycle_detection():
    g = DependencyGraph()
    g.add_node("A", NodeType.program)
    g.add_node("B", NodeType.program)
    g.add_edge("A", "B", EdgeType.call)
    g.add_edge("B", "A", EdgeType.call)
    cycles = g.find_cycles()
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}


def test_self_loop_is_a_cycle():
    g = DependencyGraph()
    g.add_node("A", NodeType.program)
    g.add_edge("A", "A", EdgeType.call)
    assert [["A"]] == g.find_cycles()


def test_no_false_cycle_on_dag():
    g = DependencyGraph()
    for n in ("A", "B", "C"):
        g.add_node(n, NodeType.program)
    g.add_edge("A", "B", EdgeType.call)
    g.add_edge("A", "C", EdgeType.call)
    g.add_edge("B", "C", EdgeType.call)
    assert g.find_cycles() == []


def test_orphans_and_unused_and_unresolved():
    g = DependencyGraph()
    g.add_node("MAIN", NodeType.program)
    g.add_node("SUB", NodeType.program)
    g.add_node("USEDCPY", NodeType.copybook)
    g.add_node("DEADCPY", NodeType.copybook)
    g.add_edge("MAIN", "SUB", EdgeType.call)
    g.add_edge("MAIN", "USEDCPY", EdgeType.copy)
    g.add_edge("MAIN", "GHOST", EdgeType.call)  # GHOST undefined -> external
    # MAIN has no incoming -> orphan; SUB is called; DEADCPY unused; GHOST unresolved.
    assert g.orphans() == ["MAIN"]
    assert g.unused_copybooks() == ["DEADCPY"]
    assert g.unresolved_references() == ["GHOST"]


def test_external_node_created_for_unresolved_edge():
    g = DependencyGraph()
    g.add_node("A", NodeType.program)
    g.add_edge("A", "EXT", EdgeType.call)
    assert g.nodes["EXT"].type is NodeType.external
    assert g.nodes["EXT"].defined is False


# --------------------------------------------------------------------------- #
# JCL link extraction
# --------------------------------------------------------------------------- #
def test_jcl_link_extraction():
    text = (FIXTURES / "jcl" / "RUNPAY.jcl").read_text(encoding="utf-8")
    links = extract_jcl_links(text, fallback_name="RUNPAY")
    assert links.job_name == "RUNPAY"
    assert ("PAYROLL", 2) in links.programs
    dsns = {d for d, _ in links.datasets}
    assert "PROD.LOADLIB" in dsns
    assert "PROD.EMP.MASTER" in dsns


# --------------------------------------------------------------------------- #
# Emitters
# --------------------------------------------------------------------------- #
def _sample_graph():
    g = DependencyGraph()
    g.add_node("PAYROLL", NodeType.program)
    g.add_node("EMPREC", NodeType.copybook)
    g.add_edge("PAYROLL", "EMPREC", EdgeType.copy)
    g.add_edge("PAYROLL", "TAXCALC", EdgeType.call)  # external
    return g


def test_dot_emitter():
    dot = to_dot(_sample_graph())
    assert dot.startswith("digraph legacylens {")
    assert "PAYROLL" in dot and "EMPREC" in dot
    assert "->" in dot


def test_mermaid_emitter():
    mmd = to_mermaid(_sample_graph())
    assert mmd.startswith("graph LR")
    assert "-->" in mmd


def test_graphml_is_well_formed_xml():
    xml_text = to_graphml(_sample_graph())
    # Will raise if not well-formed.
    dom = xml.dom.minidom.parseString(xml_text)
    assert dom.getElementsByTagName("node")
    assert dom.getElementsByTagName("edge")


# --------------------------------------------------------------------------- #
# End-to-end builder over the fixture estate
# --------------------------------------------------------------------------- #
def test_build_graph_from_fixtures(tmp_path):
    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES, estate)
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol", "jcl"]).index(estate)

    g = build_graph(store)
    store.close()

    # Nodes: PAYROLL (program), EMPREC (copybook), RUNPAY (job),
    # TAXCALC (external program), plus datasets from DD DSN.
    assert g.nodes["PAYROLL"].type is NodeType.program
    assert g.nodes["EMPREC"].type is NodeType.copybook
    assert g.nodes["RUNPAY"].type is NodeType.job
    assert g.nodes["TAXCALC"].type is NodeType.external

    edge_set = {(e.src, e.dst, e.type) for e in g.edges}
    assert ("PAYROLL", "EMPREC", EdgeType.copy) in edge_set
    assert ("PAYROLL", "TAXCALC", EdgeType.call) in edge_set
    assert ("RUNPAY", "PAYROLL", EdgeType.exec) in edge_set

    # PAYROLL is EXEC'd by RUNPAY, so it is not an orphan.
    assert "PAYROLL" not in g.orphans()
    assert "TAXCALC" in g.unresolved_references()
