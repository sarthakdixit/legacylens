"""Tests for B7: token budget, JCL & PL/I parsers, and embedding retrieval."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from legacylens.config import Config
from legacylens.errors import BudgetExceededError
from legacylens.ingest import Indexer
from legacylens.llm import EmbeddingResponse, build_gateway
from legacylens.llm.base import CompletionRequest, Message
from legacylens.parsing import JclParser, PliParser
from legacylens.retrieval import Retriever
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# Token budget
# --------------------------------------------------------------------------- #
class _UsageTransport:
    def post_json(self, url, headers, payload, timeout=60.0):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 4},
        }


def _budget_gateway(max_tokens):
    cfg = Config.model_validate(
        {
            "version": 1,
            "project": {"name": "t"},
            "languages": ["cobol"],
            "llm": {
                "providers": [{"name": "local", "type": "local", "model": "m", "base_url": "http://localhost:1/v1"}],
                "routing": {"default": "local"},
            },
            "budget": {"max_tokens": max_tokens},
        }
    )
    return build_gateway(cfg, transport=_UsageTransport(), use_cache=False)


def _small_req():
    return CompletionRequest(messages=[Message("user", "hi")], max_tokens=2)


def test_budget_tracks_tokens_spent():
    gw = _budget_gateway(None)  # unlimited
    gw.complete("default", _small_req())
    assert gw.tokens_spent == 8  # 4 + 4 from usage


def test_budget_blocks_when_exhausted():
    gw = _budget_gateway(10)
    gw.complete("default", _small_req())  # spends 8, ok
    with pytest.raises(BudgetExceededError):
        gw.complete("default", _small_req())  # would exceed 10


# --------------------------------------------------------------------------- #
# JCL parser
# --------------------------------------------------------------------------- #
def test_jcl_parser_steps_and_dds():
    job = JclParser().parse((FIXTURES / "jcl" / "MULTI.jcl").read_text(), fallback_name="MULTI")
    assert job.name == "MULTI"
    assert [s.name for s in job.steps] == ["STEP1", "STEP2"]
    assert [s.pgm for s in job.steps] == ["PROG1", "PROG2"]
    dsns = {d for d, _ in job.datasets()}
    assert dsns == {"PROD.FILE1", "PROD.FILE2"}
    # DISP captured on the second DD
    out_dd = job.steps[1].dds[0]
    assert out_dd.disp is not None and "NEW" in out_dd.disp


def test_jcl_continuation_is_merged():
    # The JOB card spans two physical lines; the parser must still see one JOB.
    job = JclParser().parse((FIXTURES / "jcl" / "MULTI.jcl").read_text())
    assert job.name == "MULTI"


def test_jcl_comment_lines_ignored():
    text = "//J JOB\n//*  EXEC PGM=GHOST\n//S EXEC PGM=REAL\n"
    job = JclParser().parse(text)
    assert [s.pgm for s in job.steps] == ["REAL"]


# --------------------------------------------------------------------------- #
# PL/I parser
# --------------------------------------------------------------------------- #
def test_pli_parser_structure():
    prog = PliParser().parse((FIXTURES / "pli" / "REPORTX.pli").read_text())
    assert prog.name == "REPORTX"  # the OPTIONS(MAIN) procedure
    proc_names = {p.name for p in prog.procedures}
    assert {"REPORTX", "LOADCUST"} <= proc_names
    assert any(p.is_main and p.name == "REPORTX" for p in prog.procedures)
    call_targets = {t for t, _ in prog.calls}
    assert {"LOADCUST", "PRINTRPT"} <= call_targets
    assert ("CUSTREC", 5) in [(n, ln) for n, ln in prog.includes] or any(n == "CUSTREC" for n, _ in prog.includes)
    assert prog.declare_count >= 3


def test_pli_block_comment_ignored():
    prog = PliParser().parse(" M: PROC OPTIONS(MAIN); /* CALL GHOST; */ CALL REAL; END M;")
    targets = {t for t, _ in prog.calls}
    assert "REAL" in targets
    assert "GHOST" not in targets


def test_pli_procedure_label_on_separate_line():
    # Real-world (PLI-2000): the label and PROCEDURE/PROC keyword are on separate
    # lines, and CALLs target internal procedures.
    src = (
        "largetst:\n"
        "   procedure options (main);\n"
        "   call run_inner_proc;\n"
        "run_inner_proc:\n"
        "   proc;\n"
        "   end run_inner_proc;\n"
        "end largetst;\n"
    )
    prog = PliParser().parse(src, fallback_name="X")
    assert prog.name == "LARGETST"  # the OPTIONS(MAIN) procedure, not the filename
    names = {p.name for p in prog.procedures}
    assert {"LARGETST", "RUN_INNER_PROC"} <= names
    assert any(p.is_main and p.name == "LARGETST" for p in prog.procedures)
    # RUN_INNER_PROC is an internal procedure, so the builder resolves the CALL
    # internally rather than as a cross-program edge.
    assert "RUN_INNER_PROC" in {t for t, _ in prog.calls}


def test_pli_call_inside_string_literal_is_ignored():
    # Real-world false positive from the PLI-2000 compiler test corpus.
    prog = PliParser().parse(
        " M: PROC OPTIONS(MAIN);\n   PUT LIST('CALL THE PROC FAILED');\n   CALL REALSUB;\n END M;"
    )
    targets = {t for t, _ in prog.calls}
    assert "REALSUB" in targets
    assert "THE" not in targets  # 'CALL THE' was inside a string literal


# --------------------------------------------------------------------------- #
# Embedding retrieval (stub gateway)
# --------------------------------------------------------------------------- #
class StubGateway:
    """Embeds text into a 3-dim keyword presence vector; deterministic, offline."""

    def __init__(self):
        self.embed_calls = 0

    def embed(self, texts):
        self.embed_calls += 1
        vecs = []
        for t in texts:
            u = t.upper()
            vecs.append([
                1.0 if "PAYROLL" in u else 0.0,
                1.0 if "TAXCALC" in u else 0.0,
                1.0 if "EMPLOYEE" in u else 0.0,
            ])
        return EmbeddingResponse(vectors=vecs, model="stub", provider="stub")


def _indexed(tmp_path) -> IndexStore:
    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES / "cobol", estate)
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol"]).index(estate)
    return store


def test_retriever_build_and_search(tmp_path):
    store = _indexed(tmp_path)
    retr = Retriever(store, StubGateway())
    stats = retr.build(["cobol"])
    assert stats.embedded == 2  # PAYROLL.cbl + EMPREC.cpy
    hits = retr.search("payroll processing run", k=2)
    assert hits[0].rel_path.endswith("PAYROLL.cbl")
    store.close()


def test_retriever_incremental_skips_unchanged(tmp_path):
    store = _indexed(tmp_path)
    retr = Retriever(store, StubGateway())
    retr.build(["cobol"])
    stats2 = retr.build(["cobol"])  # nothing changed
    assert stats2.embedded == 0
    assert stats2.skipped == 2
    store.close()
