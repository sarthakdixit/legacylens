"""Build a :class:`DependencyGraph` from the indexed artifacts.

Two passes: first define every node we have source for (programs, copybooks, jobs),
then add edges — resolving ``CALL``/``COPY``/``EXEC``/``DD`` targets against the
defined nodes and materializing external placeholders for anything unresolved.
"""

from __future__ import annotations

from pathlib import Path

from ..parsing import CobolParser, PliParser
from ..store import IndexStore
from .jcl_links import extract_jcl_links
from .model import DependencyGraph, EdgeType, NodeType


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _copybook_member(rel_path: str) -> str:
    """COPY references use the member name, i.e. the filename without extension."""
    return Path(rel_path).stem.upper()


def build_graph(store: IndexStore, parser: CobolParser | None = None) -> DependencyGraph:
    parser = parser or CobolParser()
    graph = DependencyGraph()

    cobol = store.list_artifacts("cobol")
    jcl = store.list_artifacts("jcl")
    pli = store.list_artifacts("pli")

    # ---- pass 1: define nodes, remember per-artifact parse results -------- #
    program_links: list[tuple[str, object]] = []  # (node_name, CobolProgram)
    for art in cobol:
        text = _read(art.abs_path)
        if text is None:
            continue
        prog = parser.parse(text, source_path=art.abs_path, kind=art.kind).program
        if prog.is_copybook:
            member = _copybook_member(art.rel_path)
            # Namespace copybook keys so a copybook and a same-named program (common
            # for CICS commarea copybooks) stay distinct and don't form false cycles.
            graph.add_node(member, NodeType.copybook, source_path=art.rel_path, key=f"copy:{member}")
        else:
            name = prog.program_id or _copybook_member(art.rel_path)
            graph.add_node(name, NodeType.program, source_path=art.rel_path)
            program_links.append((name, prog))

    pli_parser = PliParser()
    pli_links: list[tuple[str, object]] = []  # (node_name, PliProgram)
    for art in pli:
        text = _read(art.abs_path)
        if text is None:
            continue
        pliprog = pli_parser.parse(text, source_path=art.abs_path, fallback_name=Path(art.rel_path).stem)
        name = pliprog.name or _copybook_member(art.rel_path)
        graph.add_node(name, NodeType.program, source_path=art.rel_path)
        pli_links.append((name, pliprog))

    jcl_links = []
    for art in jcl:
        text = _read(art.abs_path)
        if text is None:
            continue
        links = extract_jcl_links(text, fallback_name=Path(art.rel_path).stem)
        # Namespace job keys so a job named like the program it runs stays distinct.
        job_key = f"job:{links.job_name}"
        graph.add_node(links.job_name, NodeType.job, source_path=art.rel_path, key=job_key)
        jcl_links.append((art.rel_path, links, job_key))

    # ---- pass 2: add edges ------------------------------------------------ #
    for name, prog in program_links:
        rel = prog.source_path
        for copy in prog.copies:
            graph.add_edge(name, f"copy:{copy.name}", EdgeType.copy, source_path=rel, line=copy.line)
        for call in prog.calls:
            if call.mechanism.startswith("CICS"):
                edge_type = EdgeType.cics
            elif call.dynamic:
                edge_type = EdgeType.dynamic_call
            else:
                edge_type = EdgeType.call
            graph.add_edge(name, call.target, edge_type, source_path=rel, line=call.line)
        for tbl in prog.sql_tables:
            graph.add_node(tbl.name, NodeType.table, key=f"table:{tbl.name}")
            graph.add_edge(name, f"table:{tbl.name}", EdgeType.sql, source_path=rel, line=tbl.line)

    for name, pliprog in pli_links:
        rel = pliprog.source_path
        # PL/I CALL is usually to an INTERNAL procedure; only treat targets that
        # are not declared in this file as cross-program (external) references.
        internal = {p.name for p in pliprog.procedures}
        for target, line in pliprog.calls:
            if target in internal:
                continue
            graph.add_edge(name, target, EdgeType.call, source_path=rel, line=line)
        for inc, line in pliprog.includes:
            graph.add_edge(name, f"copy:{inc}", EdgeType.copy, source_path=rel, line=line)

    for rel_path, links, job_key in jcl_links:
        for pgm, line in links.programs:
            graph.add_edge(job_key, pgm, EdgeType.exec, source_path=rel_path, line=line)
        for dsn, line in links.datasets:
            graph.add_node(dsn, NodeType.dataset)
            graph.add_edge(job_key, dsn, EdgeType.dd, source_path=rel_path, line=line)

    return graph
