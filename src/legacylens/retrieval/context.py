"""Retrieval-augmented context for LLM prompts.

Given a query (e.g. a program's name + structural signature), returns short excerpts
of the most semantically-similar *other* artifacts, using the BYO-embeddings index.
Downstream LLM steps (documentation, and optionally security) inject these so the
model reasons about an artifact in the context of related code — the point of the
embedding index at scale.

Degrades gracefully: if no embeddings have been built (`legacylens embed`), or no
embeddings provider is configured, :meth:`related` returns an empty list and callers
proceed without augmentation.
"""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from .retriever import Retriever

log = get_logger()


class ContextProvider:
    def __init__(self, store, gateway, k: int = 3, snippet_chars: int = 800):
        self.store = store
        self.gateway = gateway
        self.k = k
        self.snippet_chars = snippet_chars
        self._retriever = Retriever(store, gateway)

    def has_embeddings(self) -> bool:
        return next(self.store.iter_embeddings(), None) is not None

    def related(self, query: str, exclude_rel: str | None = None) -> list[tuple[str, str]]:
        """Return up to k (rel_path, snippet) pairs most relevant to ``query``,
        excluding ``exclude_rel``. Empty if retrieval is unavailable."""
        try:
            hits = self._retriever.search(query, k=self.k + 1)
        except Exception as exc:  # embeddings not built / provider error
            log.debug("retrieval context unavailable: %s", exc)
            return []

        out: list[tuple[str, str]] = []
        for hit in hits:
            if exclude_rel and hit.rel_path == exclude_rel:
                continue
            artifact = self.store.get(hit.rel_path)
            if artifact is None:
                continue
            try:
                text = Path(artifact.abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.append((hit.rel_path, text[: self.snippet_chars]))
            if len(out) >= self.k:
                break
        return out
