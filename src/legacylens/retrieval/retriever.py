"""Embedding-based retriever.

``build`` embeds a snippet of each artifact (incrementally — unchanged content is
skipped) and stores the vectors. ``search`` embeds a query and returns the top-k
artifacts by cosine similarity. Embedding is batched to limit the number of provider
round-trips.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger
from ..store import IndexStore

log = get_logger()

# Characters of each artifact used to build its embedding (keeps requests bounded).
_SNIPPET_CHARS = 4000
_BATCH = 32


@dataclass
class BuildStats:
    embedded: int = 0
    skipped: int = 0


@dataclass
class SearchHit:
    rel_path: str
    score: float


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class Retriever:
    def __init__(self, store: IndexStore, gateway):
        self.store = store
        self.gateway = gateway

    def build(self, languages: list[str] | None = None) -> BuildStats:
        stats = BuildStats()
        batch: list[tuple[str, str, str]] = []  # (rel_path, sha, snippet)

        def flush():
            if not batch:
                return
            vectors = self.gateway.embed([snip for _, _, snip in batch]).vectors
            for (rel_path, sha, _), vec in zip(batch, vectors):
                self.store.save_embedding(rel_path, sha, vec)
                stats.embedded += 1
            batch.clear()

        langs = languages or ["cobol", "jcl", "pli"]
        for lang in langs:
            for art in self.store.iter_artifacts(lang):
                if self.store.embedding_sha(art.rel_path) == art.sha256:
                    stats.skipped += 1
                    continue
                try:
                    text = Path(art.abs_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                batch.append((art.rel_path, art.sha256, text[:_SNIPPET_CHARS]))
                if len(batch) >= _BATCH:
                    flush()
        flush()
        return stats

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        qvec = self.gateway.embed([query]).vectors[0]
        scored = [
            SearchHit(rel_path=rel_path, score=_cosine(qvec, vec))
            for rel_path, vec in self.store.iter_embeddings()
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]
