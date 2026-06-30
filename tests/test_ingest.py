"""Tests for ingestion: classification, discovery, incremental indexing (B2 gate)."""

from __future__ import annotations

from pathlib import Path

from legacylens.ingest import Indexer, classify, discover
from legacylens.store import IndexStore

# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def test_classify_by_extension():
    assert classify("PAYROLL.cbl", b"anything").language == "cobol"
    assert classify("EMPREC.cpy", b"x").kind == "copybook"
    assert classify("RUNPAY.jcl", b"x").language == "jcl"
    assert classify("MOD.pli", b"x").language == "pli"


def test_classify_cobol_by_content_no_extension():
    src = b"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. FOO.\n"
    result = classify("FOO", src)
    assert result.language == "cobol"
    assert result.method == "content"


def test_classify_jcl_by_content_no_extension():
    src = b"//MYJOB JOB (1),'X'\n//S1 EXEC PGM=FOO\n"
    result = classify("MYJOB", src)
    assert result.language == "jcl"


def test_classify_binary_is_unknown():
    assert classify("data", b"\x00\x01\x02BINARY").language is None


def test_classify_plaintext_is_unknown():
    assert classify("notes.txt", b"just some prose, nothing mainframe here").language is None


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _build_estate(base: Path):
    (base / "src").mkdir(parents=True)
    (base / "src" / "A.cbl").write_text("       PROGRAM-ID. A.\n", encoding="utf-8")
    (base / "src" / "B.jcl").write_text("//B JOB\n//S EXEC PGM=A\n", encoding="utf-8")
    (base / "src" / "notes.txt").write_text("hello", encoding="utf-8")
    (base / "src" / "test").mkdir()
    (base / "src" / "test" / "T.cbl").write_text("       PROGRAM-ID. T.\n", encoding="utf-8")


def test_discover_respects_excludes(tmp_path):
    _build_estate(tmp_path)
    found = {p.name for p in discover(tmp_path / "src", exclude=["**/test/**"])}
    assert "A.cbl" in found
    assert "B.jcl" in found
    assert "T.cbl" not in found  # excluded


def test_discover_skips_vcs_dirs(tmp_path):
    _build_estate(tmp_path)
    (tmp_path / "src" / ".git").mkdir()
    (tmp_path / "src" / ".git" / "config").write_text("x", encoding="utf-8")
    found = {p.name for p in discover(tmp_path / "src")}
    assert "config" not in found


# --------------------------------------------------------------------------- #
# Indexing (incremental)
# --------------------------------------------------------------------------- #
def _indexer(tmp_path):
    store = IndexStore(tmp_path / "index.db")
    return store, Indexer(store, ["cobol", "jcl"])


def test_index_first_run_adds(tmp_path):
    _build_estate(tmp_path)
    store, idx = _indexer(tmp_path)
    stats = idx.index(tmp_path / "src", exclude=["**/test/**"])
    assert stats.added == 2  # A.cbl + B.jcl
    assert stats.updated == 0
    assert stats.skipped_unknown == 1  # notes.txt
    assert store.counts_by_language() == {"cobol": 1, "jcl": 1}
    store.close()


def test_index_second_run_unchanged(tmp_path):
    _build_estate(tmp_path)
    store, idx = _indexer(tmp_path)
    idx.index(tmp_path / "src", exclude=["**/test/**"])
    stats = idx.index(tmp_path / "src", exclude=["**/test/**"])
    assert stats.added == 0
    assert stats.unchanged == 2
    store.close()


def test_index_detects_modification(tmp_path):
    _build_estate(tmp_path)
    store, idx = _indexer(tmp_path)
    idx.index(tmp_path / "src", exclude=["**/test/**"])
    (tmp_path / "src" / "A.cbl").write_text("       PROGRAM-ID. A.\n       DISPLAY 'X'.\n", encoding="utf-8")
    stats = idx.index(tmp_path / "src", exclude=["**/test/**"])
    assert stats.updated == 1
    assert stats.unchanged == 1
    store.close()


def test_index_detects_addition_and_removal(tmp_path):
    _build_estate(tmp_path)
    store, idx = _indexer(tmp_path)
    idx.index(tmp_path / "src", exclude=["**/test/**"])
    # add one, remove one
    (tmp_path / "src" / "C.cbl").write_text("       PROGRAM-ID. C.\n", encoding="utf-8")
    (tmp_path / "src" / "B.jcl").unlink()
    stats = idx.index(tmp_path / "src", exclude=["**/test/**"])
    assert stats.added == 1
    assert stats.removed == 1
    assert "C.cbl" in store.active_paths()
    assert "B.jcl" not in store.active_paths()
    store.close()


def test_index_skips_disabled_language(tmp_path):
    _build_estate(tmp_path)
    store = IndexStore(tmp_path / "index.db")
    idx = Indexer(store, ["cobol"])  # jcl disabled
    stats = idx.index(tmp_path / "src", exclude=["**/test/**"])
    assert stats.added == 1  # only A.cbl
    assert stats.skipped_disabled == 1  # B.jcl out of scope
    store.close()
