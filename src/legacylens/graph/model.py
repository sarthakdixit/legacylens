"""Graph data model and structural analyses.

Nodes are keyed by their symbolic name (a COBOL ``PROGRAM-ID``, a copybook member
name, a JCL job name, a dataset DSN). Edges record where the reference came from
(artifact + line) so findings and docs can cite it. Analyses are pure functions over
the graph: cycle detection (Tarjan SCC), orphan/unused detection, and unresolved
references.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class NodeType(str, enum.Enum):
    program = "program"
    copybook = "copybook"
    job = "job"
    dataset = "dataset"
    external = "external"  # referenced but no source found


class EdgeType(str, enum.Enum):
    call = "call"
    dynamic_call = "dynamic_call"
    copy = "copy"
    exec = "exec"
    dd = "dd"


# Edge kinds that represent a code/control dependency for cycle purposes.
_DEPENDENCY_EDGES = {EdgeType.call, EdgeType.copy, EdgeType.exec}


@dataclass
class Node:
    name: str
    type: NodeType
    defined: bool = False  # True when we have source for it
    source_paths: list[str] = field(default_factory=list)


@dataclass
class Edge:
    src: str
    dst: str
    type: EdgeType
    source_path: str | None = None
    line: int = 0


class DependencyGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []

    # -- construction ------------------------------------------------------- #
    def add_node(self, name: str, type: NodeType, source_path: str | None = None) -> Node:
        node = self.nodes.get(name)
        if node is None:
            node = Node(name=name, type=type)
            self.nodes[name] = node
        # A definition upgrades an external placeholder to its real type.
        if type is not NodeType.external:
            node.type = type
            node.defined = True
        if source_path and source_path not in node.source_paths:
            node.source_paths.append(source_path)
        return node

    def add_edge(self, src: str, dst: str, type: EdgeType, source_path: str | None = None, line: int = 0) -> None:
        if dst not in self.nodes:
            # Referenced but undefined → external placeholder.
            self.nodes[dst] = Node(name=dst, type=NodeType.external)
        self.edges.append(Edge(src=src, dst=dst, type=type, source_path=source_path, line=line))

    # -- queries ------------------------------------------------------------ #
    def _adjacency(self, edge_types: set[EdgeType] | None = None) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {name: [] for name in self.nodes}
        for e in self.edges:
            if edge_types is None or e.type in edge_types:
                adj[e.src].append(e.dst)
        return adj

    def incoming_counts(self, edge_types: set[EdgeType] | None = None) -> dict[str, int]:
        counts: dict[str, int] = {name: 0 for name in self.nodes}
        for e in self.edges:
            if edge_types is None or e.type in edge_types:
                counts[e.dst] = counts.get(e.dst, 0) + 1
        return counts

    # -- analyses ----------------------------------------------------------- #
    def find_cycles(self) -> list[list[str]]:
        """Return dependency cycles as lists of node names (Tarjan SCCs of size > 1,
        plus self-loops)."""
        adj = self._adjacency(_DEPENDENCY_EDGES)
        index_counter = [0]
        stack: list[str] = []
        on_stack: dict[str, bool] = {}
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        sccs: list[list[str]] = []

        def strongconnect(v: str) -> None:
            indices[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack[v] = True
            for w in adj.get(v, []):
                if w not in indices:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif on_stack.get(w):
                    lowlink[v] = min(lowlink[v], indices[w])
            if lowlink[v] == indices[v]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    component.append(w)
                    if w == v:
                        break
                sccs.append(component)

        for v in self.nodes:
            if v not in indices:
                strongconnect(v)

        cycles = [scc for scc in sccs if len(scc) > 1]
        # self-loops (a node that depends on itself)
        selfloops = {e.src for e in self.edges if e.src == e.dst and e.type in _DEPENDENCY_EDGES}
        cycles.extend([[n] for n in selfloops])
        return cycles

    def orphans(self) -> list[str]:
        """Defined programs with no incoming references (not called, not EXEC'd).
        Jobs are entry points and excluded."""
        incoming = self.incoming_counts({EdgeType.call, EdgeType.exec})
        return sorted(
            n.name
            for n in self.nodes.values()
            if n.type is NodeType.program and n.defined and incoming.get(n.name, 0) == 0
        )

    def unused_copybooks(self) -> list[str]:
        incoming = self.incoming_counts({EdgeType.copy})
        return sorted(
            n.name
            for n in self.nodes.values()
            if n.type is NodeType.copybook and n.defined and incoming.get(n.name, 0) == 0
        )

    def unresolved_references(self) -> list[str]:
        """Names that are referenced but have no source (external nodes)."""
        return sorted(n.name for n in self.nodes.values() if n.type is NodeType.external)
