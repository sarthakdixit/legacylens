"""Semantic retrieval over the estate using bring-your-own embeddings.

For large estates a single artifact's context (or the whole codebase) won't fit in a
model's window. The :class:`Retriever` builds an embedding index — one vector per
artifact, via the configured BYO/local embeddings provider — and serves nearest-
neighbour lookups so analysis/documentation can select only the most relevant
artifacts as context. Vectors persist in the embedded SQLite store and are rebuilt
incrementally (skipped when an artifact's content hash is unchanged).
"""

from .context import ContextProvider
from .retriever import Retriever

__all__ = ["Retriever", "ContextProvider"]
