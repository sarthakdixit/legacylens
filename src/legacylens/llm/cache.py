"""Content-addressed cache for LLM results.

Keyed by a SHA-256 over (provider, model, kind, request signature), so identical
requests to the same model return instantly without re-billing tokens. Backed by
SQLite for zero-dependency, concurrency-safe, on-disk persistence — important for
large estates where the same artifact may be analyzed repeatedly.

Caching only deterministic-by-intent calls is the caller's responsibility; the
gateway caches completions at ``temperature == 0`` by default.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def make_key(provider: str, model: str, kind: str, signature: dict[str, Any]) -> str:
    blob = json.dumps(
        {"provider": provider, "model": model, "kind": kind, "sig": signature},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class LLMCache:
    """SQLite-backed key/value store of serialized LLM responses."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL,"
            " created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        self._conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT value FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class NullCache:
    """No-op cache used when caching is disabled."""

    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass
