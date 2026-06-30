"""Modern documentation generation.

Produces Markdown docs from the structural model (B3) and dependency graph (B4):
one document per artifact (purpose, dependencies, structure, business logic) plus a
system-level overview that embeds the Mermaid dependency graph and the security
summary. Natural-language sections come from the LLM when available and are clearly
labelled as inferred (and flagged for review); without an LLM, a deterministic
structural description is produced instead. Every fact cites its source location.
"""

from .generator import DocGenerator

__all__ = ["DocGenerator"]
