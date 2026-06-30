"""Ingestion: discover source files, classify them, and index them.

Pipeline: :func:`~legacylens.ingest.discovery.discover` walks the project root and
applies exclude globs; :func:`~legacylens.ingest.classify.classify` assigns a language
and kind (extension-first, content-heuristic fallback for extensionless mainframe
members); :class:`~legacylens.ingest.indexer.Indexer` hashes content and upserts into
the persistent store, computing what changed since the last run.
"""

from .classify import Classification, classify
from .discovery import discover
from .indexer import IndexStats, Indexer

__all__ = ["discover", "classify", "Classification", "Indexer", "IndexStats"]
