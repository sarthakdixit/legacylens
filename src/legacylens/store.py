"""Persistent index store (embedded SQLite).

Holds one row per in-scope source artifact: its path, language/kind, content hash,
size, and modification time. The content hash is what makes re-indexing incremental
— an artifact whose ``sha256`` is unchanged is skipped by every downstream stage.

Embedded SQLite is deliberate: zero external dependencies, trivially shippable in an
air-gapped environment, and able to hold millions of rows for large estates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class Artifact:
    rel_path: str
    abs_path: str
    language: str
    kind: str
    sha256: str
    size_bytes: int
    mtime: float
    status: str = "active"


class IndexStore:
    """SQLite-backed artifact index."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                rel_path   TEXT PRIMARY KEY,
                abs_path   TEXT NOT NULL,
                language   TEXT NOT NULL,
                kind       TEXT NOT NULL,
                sha256     TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime      REAL NOT NULL,
                indexed_at TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'active'
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_language ON artifacts(language);
            CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS embeddings (
                rel_path TEXT PRIMARY KEY,
                sha256   TEXT NOT NULL,
                vector   TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    # -- reads -------------------------------------------------------------- #
    def get(self, rel_path: str) -> Artifact | None:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE rel_path = ?", (rel_path,)
        ).fetchone()
        return _row_to_artifact(row) if row else None

    def active_paths(self) -> set[str]:
        rows = self._conn.execute(
            "SELECT rel_path FROM artifacts WHERE status = 'active'"
        ).fetchall()
        return {r["rel_path"] for r in rows}

    def list_artifacts(self, language: str | None = None) -> list[Artifact]:
        if language:
            rows = self._conn.execute(
                "SELECT * FROM artifacts WHERE status = 'active' AND language = ? ORDER BY rel_path",
                (language,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM artifacts WHERE status = 'active' ORDER BY rel_path"
            ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def iter_artifacts(self, language: str | None = None):
        """Stream active artifacts one row at a time (bounded memory for large estates)."""
        if language:
            cur = self._conn.execute(
                "SELECT * FROM artifacts WHERE status='active' AND language=? ORDER BY rel_path",
                (language,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM artifacts WHERE status='active' ORDER BY rel_path"
            )
        for row in cur:
            yield _row_to_artifact(row)

    def counts_by_language(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT language, COUNT(*) AS n FROM artifacts WHERE status = 'active' GROUP BY language"
        ).fetchall()
        return {r["language"]: r["n"] for r in rows}

    # -- writes ------------------------------------------------------------- #
    def upsert(self, artifact: Artifact) -> None:
        self._conn.execute(
            """
            INSERT INTO artifacts
                (rel_path, abs_path, language, kind, sha256, size_bytes, mtime, indexed_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(rel_path) DO UPDATE SET
                abs_path=excluded.abs_path,
                language=excluded.language,
                kind=excluded.kind,
                sha256=excluded.sha256,
                size_bytes=excluded.size_bytes,
                mtime=excluded.mtime,
                indexed_at=excluded.indexed_at,
                status='active'
            """,
            (
                artifact.rel_path,
                artifact.abs_path,
                artifact.language,
                artifact.kind,
                artifact.sha256,
                artifact.size_bytes,
                artifact.mtime,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def mark_removed(self, rel_paths: set[str]) -> None:
        if not rel_paths:
            return
        self._conn.executemany(
            "UPDATE artifacts SET status = 'removed' WHERE rel_path = ?",
            [(p,) for p in rel_paths],
        )
        self._conn.commit()

    # -- findings ----------------------------------------------------------- #
    def replace_findings(self, findings: list[dict]) -> None:
        """Replace all stored findings with this run's results."""
        import json

        self._conn.execute("DELETE FROM findings")
        self._conn.executemany(
            "INSERT INTO findings (data) VALUES (?)",
            [(json.dumps(f),) for f in findings],
        )
        self._conn.commit()

    def list_findings(self) -> list[dict]:
        import json

        rows = self._conn.execute("SELECT data FROM findings ORDER BY id").fetchall()
        return [json.loads(r["data"]) for r in rows]

    # -- embeddings --------------------------------------------------------- #
    def save_embedding(self, rel_path: str, sha256: str, vector: list[float]) -> None:
        import json

        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings (rel_path, sha256, vector) VALUES (?, ?, ?)",
            (rel_path, sha256, json.dumps(vector)),
        )
        self._conn.commit()

    def embedding_sha(self, rel_path: str) -> str | None:
        row = self._conn.execute(
            "SELECT sha256 FROM embeddings WHERE rel_path = ?", (rel_path,)
        ).fetchone()
        return row["sha256"] if row else None

    def iter_embeddings(self):
        """Yield (rel_path, vector) pairs one at a time."""
        import json

        for row in self._conn.execute("SELECT rel_path, vector FROM embeddings"):
            yield row["rel_path"], json.loads(row["vector"])

    def close(self) -> None:
        self._conn.close()


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        rel_path=row["rel_path"],
        abs_path=row["abs_path"],
        language=row["language"],
        kind=row["kind"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        mtime=row["mtime"],
        status=row["status"],
    )
