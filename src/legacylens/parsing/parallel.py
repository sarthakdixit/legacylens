"""Parallel parse pre-warming.

Grammar-parses cache-miss artifacts across a process pool and stores the results in
the (main-process) parse cache, so the subsequent serial pass hits a warm cache. This
is the scale lever for large estates now that parses are cached.

Design constraints handled:
* Workers are pure functions of ``(text, kind, backend)`` — no SQLite handle and no
  LLM gateway crosses a process boundary (neither is picklable).
* Only high-confidence results are cached; low-confidence artifacts are left uncached
  so the serial pass can still apply the LLM fallback (which needs the gateway).
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger
from .cache import parse_cache_key
from .factory import build_cobol_parser
from .serialize import parseresult_to_dict

log = get_logger()

# Below this many misses, pool startup isn't worth it — let the serial pass handle it.
_MIN_MISSES = 8
# Results below this confidence are not cached (so the serial pass can LLM-recover).
_MIN_CONFIDENCE = 0.5


@dataclass
class PrewarmStats:
    parsed: int = 0
    cached: int = 0


def _parse_worker(payload: tuple[str, str | None, str]) -> dict:
    """Runs in a worker process: parse text with a gateway-less grammar parser."""
    text, kind, backend = payload
    parser = build_cobol_parser(backend, gateway=None, fallback_to_regex=True)
    result = parser.parse(text, source_path=None, kind=kind)
    return parseresult_to_dict(result)


def prewarm_parse_cache(store, artifacts, backend: str, workers: int) -> PrewarmStats:
    """Parse cache-miss COBOL artifacts in parallel and populate the parse cache."""
    stats = PrewarmStats()
    if workers <= 1:
        return stats

    misses: list[tuple[str, str | None]] = []  # (text, kind) with cache key
    keys: list[str] = []
    for art in artifacts:
        try:
            text = Path(art.abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        key = parse_cache_key(backend, art.kind, text)
        if store.get_parse(key) is not None:
            continue
        misses.append((text, art.kind))
        keys.append(key)

    if len(misses) < _MIN_MISSES:
        return stats  # not worth the pool; serial pass will parse+cache these

    payloads = [(text, kind, backend) for text, kind in misses]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_parse_worker, payloads))
    except Exception as exc:  # restricted env, spawn failure, etc.
        log.warning("parallel parse unavailable (%s); falling back to serial.", exc)
        return stats

    for key, data in zip(keys, results):
        stats.parsed += 1
        if data.get("confidence", 1.0) >= _MIN_CONFIDENCE:
            store.put_parse(key, data)
            stats.cached += 1
    return stats
