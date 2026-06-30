"""Drives discovery + classification + hashing into the persistent index.

Computes an incremental diff against the previous run: an artifact is *unchanged*
when its content hash matches, *updated* when the hash differs, *added* when it is
new, and *removed* when a previously-indexed path is no longer present. Only files
that classify into one of the *enabled* languages are stored; everything else is
counted as skipped so the run summary is honest about coverage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..store import Artifact, IndexStore
from .classify import classify
from .discovery import discover

# Bytes read for classification heuristics (full file is hashed separately).
_SAMPLE_BYTES = 8192


@dataclass
class IndexStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped_unknown: int = 0
    skipped_disabled: int = 0
    by_language: dict[str, int] = field(default_factory=dict)

    @property
    def scanned(self) -> int:
        return self.added + self.updated + self.unchanged


def _hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


class Indexer:
    def __init__(self, store: IndexStore, enabled_languages: list[str]):
        self.store = store
        self.enabled = set(enabled_languages)

    def index(self, root: str | Path, exclude: list[str] | None = None) -> IndexStats:
        root = Path(root).resolve()
        stats = IndexStats()
        seen: set[str] = set()

        for abs_path in discover(root, exclude):
            try:
                with abs_path.open("rb") as fh:
                    sample = fh.read(_SAMPLE_BYTES)
            except OSError:
                continue  # unreadable file; skip silently (counted as not-seen)

            result = classify(abs_path.name, sample)
            if result.language is None:
                stats.skipped_unknown += 1
                continue
            if result.language not in self.enabled:
                stats.skipped_disabled += 1
                continue

            rel_path = abs_path.relative_to(root).as_posix()
            seen.add(rel_path)

            sha256, size = _hash_file(abs_path)
            existing = self.store.get(rel_path)
            if existing and existing.status == "active" and existing.sha256 == sha256:
                stats.unchanged += 1
            elif existing:
                stats.updated += 1
            else:
                stats.added += 1

            self.store.upsert(
                Artifact(
                    rel_path=rel_path,
                    abs_path=str(abs_path),
                    language=result.language,
                    kind=result.kind,
                    sha256=sha256,
                    size_bytes=size,
                    mtime=abs_path.stat().st_mtime,
                )
            )
            stats.by_language[result.language] = stats.by_language.get(result.language, 0) + 1

        # Anything previously active but not seen this run is now removed.
        stale = self.store.active_paths() - seen
        self.store.mark_removed(stale)
        stats.removed = len(stale)
        return stats
