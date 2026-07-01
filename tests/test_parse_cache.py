"""Tests for the persistent, content-addressed parse cache."""

from __future__ import annotations

from pathlib import Path

from legacylens.parsing import CobolParser
from legacylens.parsing.cache import CachingCobolParser
from legacylens.parsing.serialize import parseresult_from_dict, parseresult_to_dict
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


def _payroll() -> str:
    return (FIXTURES / "cobol" / "PAYROLL.cbl").read_text()


class _CountingParser:
    """Base parser that counts how many times it actually parses."""

    def __init__(self):
        self.calls = 0
        self._inner = CobolParser()

    def parse(self, text, source_path=None, kind=None):
        self.calls += 1
        return self._inner.parse(text, source_path=source_path, kind=kind)


# --------------------------------------------------------------------------- #
# Serialization round-trip
# --------------------------------------------------------------------------- #
def test_parseresult_serialization_round_trip():
    result = CobolParser().parse(_payroll(), source_path="a.cbl", kind="program")
    restored = parseresult_from_dict(parseresult_to_dict(result), source_path="a.cbl")
    assert restored.program.program_id == result.program.program_id
    assert restored.method == result.method
    assert {p.name for p in restored.program.paragraphs} == {p.name for p in result.program.paragraphs}
    assert {c.target for c in restored.program.calls} == {c.target for c in result.program.calls}
    assert {d.name for d in restored.program.data_items} == {d.name for d in result.program.data_items}


# --------------------------------------------------------------------------- #
# Caching behavior
# --------------------------------------------------------------------------- #
def test_second_parse_hits_cache(tmp_path):
    store = IndexStore(tmp_path / "index.db")
    base = _CountingParser()
    cp = CachingCobolParser(base, store, backend="regex")

    r1 = cp.parse(_payroll(), source_path="a.cbl", kind="program")
    r2 = cp.parse(_payroll(), source_path="a.cbl", kind="program")
    store.close()

    assert base.calls == 1  # underlying parser ran once
    assert cp.hits == 1 and cp.misses == 1
    assert r1.program.program_id == r2.program.program_id == "PAYROLL"


def test_cache_persists_across_parser_instances(tmp_path):
    dbp = tmp_path / "index.db"
    store = IndexStore(dbp)
    base1 = _CountingParser()
    CachingCobolParser(base1, store, backend="regex").parse(_payroll(), kind="program")
    store.close()

    # New store + parser (simulates a later run) — should hit the persisted cache.
    store2 = IndexStore(dbp)
    base2 = _CountingParser()
    cp2 = CachingCobolParser(base2, store2, backend="regex")
    cp2.parse(_payroll(), kind="program")
    store2.close()
    assert base2.calls == 0  # served entirely from the persisted cache
    assert cp2.hits == 1


def test_changed_content_misses_cache(tmp_path):
    store = IndexStore(tmp_path / "index.db")
    base = _CountingParser()
    cp = CachingCobolParser(base, store, backend="regex")
    cp.parse(_payroll(), kind="program")
    cp.parse(_payroll() + "\n       DISPLAY 'X'.\n", kind="program")  # different content
    store.close()
    assert base.calls == 2  # re-parsed on change


def test_different_backend_key_is_separate(tmp_path):
    store = IndexStore(tmp_path / "index.db")
    base = _CountingParser()
    CachingCobolParser(base, store, backend="regex").parse(_payroll(), kind="program")
    # Same content, different backend label → distinct cache key → miss.
    cp2 = CachingCobolParser(base, store, backend="antlr")
    cp2.parse(_payroll(), kind="program")
    store.close()
    assert cp2.misses == 1


def test_use_cache_false_bypasses(tmp_path):
    store = IndexStore(tmp_path / "index.db")
    base = _CountingParser()
    cp = CachingCobolParser(base, store, backend="regex", use_cache=False)
    cp.parse(_payroll(), kind="program")
    cp.parse(_payroll(), kind="program")
    store.close()
    assert base.calls == 2  # no caching
