"""Render a :class:`DependencyGraph` to standard graph formats.

* **DOT** — Graphviz, the lingua franca for graph tooling.
* **Mermaid** — embeds directly in Markdown docs (B6).
* **GraphML** — XML, for import into graph databases / analysis tools.

Node shape/style encodes type; edge style encodes relationship (dynamic calls and
unresolved externals are visually distinct so reviewers spot them).
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from .model import DependencyGraph, EdgeType, NodeType

_DOT_SHAPES = {
    NodeType.program: "box",
    NodeType.copybook: "note",
    NodeType.job: "component",
    NodeType.dataset: "cylinder",
    NodeType.table: "cylinder",
    NodeType.external: "box",
}


def _sanitize_id(name: str) -> str:
    return "n_" + "".join(c if c.isalnum() else "_" for c in name)


def to_dot(graph: DependencyGraph) -> str:
    lines = ["digraph legacylens {", "  rankdir=LR;", '  node [fontname="monospace"];']
    for node in sorted(graph.nodes.values(), key=lambda n: n.key):
        shape = _DOT_SHAPES.get(node.type, "box")
        style = "" if node.defined else ', style=dashed, color="red"'
        label = f"{node.name}\\n({node.type.value})"
        lines.append(f'  {_sanitize_id(node.key)} [label="{label}", shape={shape}{style}];')
    for edge in graph.edges:
        attrs = f'label="{edge.type.value}"'
        if edge.type is EdgeType.dynamic_call:
            attrs += ', style=dashed'
        lines.append(f"  {_sanitize_id(edge.src)} -> {_sanitize_id(edge.dst)} [{attrs}];")
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_mermaid(graph: DependencyGraph) -> str:
    lines = ["graph LR"]
    for node in sorted(graph.nodes.values(), key=lambda n: n.key):
        nid = _sanitize_id(node.key)
        label = f"{node.name}<br/>({node.type.value})"
        if node.type in (NodeType.dataset, NodeType.table):
            lines.append(f"  {nid}[({label})]")  # rounded/cylinder-ish
        elif node.defined:
            lines.append(f"  {nid}[{label}]")
        else:
            lines.append(f"  {nid}({label})")  # external → rounded
    for edge in graph.edges:
        arrow = "-.->" if edge.type is EdgeType.dynamic_call else "-->"
        lines.append(f"  {_sanitize_id(edge.src)} {arrow}|{edge.type.value}| {_sanitize_id(edge.dst)}")
    return "\n".join(lines) + "\n"


def to_graphml(graph: DependencyGraph) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="type" for="node" attr.name="type" attr.type="string"/>',
        '  <key id="defined" for="node" attr.name="defined" attr.type="boolean"/>',
        '  <key id="rel" for="edge" attr.name="relationship" attr.type="string"/>',
        '  <graph edgedefault="directed">',
    ]
    for node in sorted(graph.nodes.values(), key=lambda n: n.key):
        out.append(f"    <node id={quoteattr(node.key)}>")
        out.append(f'      <data key="type">{escape(node.type.value)}</data>')
        out.append(f'      <data key="defined">{str(node.defined).lower()}</data>')
        out.append("    </node>")
    for i, edge in enumerate(graph.edges):
        out.append(
            f"    <edge id=\"e{i}\" source={quoteattr(edge.src)} target={quoteattr(edge.dst)}>"
        )
        out.append(f'      <data key="rel">{escape(edge.type.value)}</data>')
        out.append("    </edge>")
    out.append("  </graph>")
    out.append("</graphml>")
    return "\n".join(out) + "\n"
