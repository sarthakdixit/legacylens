"""Persistent, content-addressed parse cache.

Wraps any COBOL parser and memoizes :class:`ParseResult`s in the index DB, keyed by
(cache-version, backend, kind, sha256-of-source). Because the key is content-based,
an unchanged file is parsed once and reused across commands (analyze → graph → doc)
and across runs — the basis for incremental analysis on large estates. Changing the
parser backend or bumping ``PARSE_CACHE_VERSION`` naturally invalidates old entries.
"""

from __future__ import annotations

import hashlib

from .model import ParseResult
from .serialize import parseresult_from_dict, parseresult_to_dict

# Bump when the parsers' output shape/semantics change, to invalidate stale entries.
PARSE_CACHE_VERSION = "1"


class CachingCobolParser:
    def __init__(self, base, store, backend: str = "regex", use_cache: bool = True):
        self._base = base
        self._store = store
        self._backend = backend
        self._use_cache = use_cache
        self.hits = 0
        self.misses = 0

    # Expose the wrapped gateway (some callers pass a parser with .gateway).
    @property
    def gateway(self):
        return getattr(self._base, "gateway", None)

    def _key(self, text: str, kind: str | None) -> str:
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        return f"{PARSE_CACHE_VERSION}:{self._backend}:{kind or ''}:{digest}"

    def parse(self, text: str, source_path: str | None = None, kind: str | None = None) -> ParseResult:
        if not self._use_cache:
            return self._base.parse(text, source_path=source_path, kind=kind)

        key = self._key(text, kind)
        cached = self._store.get_parse(key)
        if cached is not None:
            self.hits += 1
            return parseresult_from_dict(cached, source_path=source_path)

        self.misses += 1
        result = self._base.parse(text, source_path=source_path, kind=kind)
        self._store.put_parse(key, parseresult_to_dict(result))
        return result
