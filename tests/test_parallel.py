"""Tests for parallel parse pre-warming."""

from __future__ import annotations

import shutil
from pathlib import Path

from legacylens.parsing.cache import CachingCobolParser, parse_cache_key
from legacylens.parsing.parallel import _parse_worker, prewarm_parse_cache
from legacylens.parsing.serialize import parseresult_from_dict
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


def _payroll_text() -> str:
    return (FIXTURES / "cobol" / "PAYROLL.cbl").read_text()


def test_worker_parses_to_dict():
    data = _parse_worker((_payroll_text(), "program", "regex"))
    restored = parseresult_from_dict(data)
    assert restored.program.program_id == "PAYROLL"
    assert data["confidence"] >= 0.9


def test_prewarm_is_noop_below_threshold(tmp_path):
    # A tiny estate (< threshold) should not spin up the pool; nothing cached.
    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES / "cobol", estate)
    store = IndexStore(tmp_path / "index.db")
    from legacylens.ingest import Indexer

    Indexer(store, ["cobol"]).index(estate)
    stats = prewarm_parse_cache(store, store.list_artifacts("cobol"), "regex", workers=2)
    store.close()
    assert stats.parsed == 0  # below _MIN_MISSES


def test_prewarm_populates_cache(tmp_path, monkeypatch):
    # Lower the threshold so the small fixture estate exercises the pool path.
    import legacylens.parsing.parallel as par

    monkeypatch.setattr(par, "_MIN_MISSES", 1)

    estate = tmp_path / "estate"
    estate.mkdir()
    # A few distinct programs to parse in parallel.
    for i in range(3):
        (estate / f"P{i}.cbl").write_text(
            f"       IDENTIFICATION DIVISION.\n"
            f"       PROGRAM-ID. P{i}.\n"
            f"       PROCEDURE DIVISION.\n"
            f"       MAIN.\n"
            f"           DISPLAY 'HELLO {i}'.\n"
            f"           GOBACK.\n",
            encoding="utf-8",
        )
    store = IndexStore(estate.parent / "index.db")
    from legacylens.ingest import Indexer

    Indexer(store, ["cobol"]).index(estate)
    arts = store.list_artifacts("cobol")

    stats = par.prewarm_parse_cache(store, arts, "regex", workers=2)
    assert stats.parsed == 3 and stats.cached == 3

    # Cache is warm: a caching parser now hits for every artifact (0 misses).
    cp = CachingCobolParser(object(), store, backend="regex")  # base won't be called

    for art in arts:
        key = parse_cache_key("regex", art.kind, Path(art.abs_path).read_text())
        assert store.get_parse(key) is not None
    store.close()
