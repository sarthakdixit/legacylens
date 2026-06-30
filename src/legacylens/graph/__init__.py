"""Dependency graph: connect artifacts across the estate.

Nodes are symbolic artifacts (programs, copybooks, JCL jobs, datasets); edges are the
relationships the parsers surface — ``CALL`` (program→program), ``COPY``
(program→copybook), ``EXEC PGM=`` (job→program), and ``DD DSN=`` (job→dataset).
Targets without source become ``external`` nodes so unresolved references are
visible rather than dropped.

The graph supports the analyses downstream stages and reports need: cycle detection,
orphan / unused-copybook detection, and listing unresolved references.
"""

from .builder import build_graph
from .emit import to_dot, to_graphml, to_mermaid
from .model import DependencyGraph, Edge, EdgeType, Node, NodeType

__all__ = [
    "build_graph",
    "DependencyGraph",
    "Node",
    "Edge",
    "NodeType",
    "EdgeType",
    "to_dot",
    "to_mermaid",
    "to_graphml",
]
