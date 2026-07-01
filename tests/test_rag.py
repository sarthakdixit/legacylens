"""Tests for retrieval-augmented LLM context (retriever wired into docs)."""

from __future__ import annotations

import shutil
from pathlib import Path

from legacylens.docs import DocGenerator
from legacylens.graph import build_graph
from legacylens.ingest import Indexer
from legacylens.llm import EmbeddingResponse
from legacylens.parsing import CobolParser
from legacylens.retrieval import ContextProvider, Retriever
from legacylens.store import IndexStore

FIXTURES = Path(__file__).parent / "fixtures"


class StubGateway:
    """Keyword-presence embeddings + a completion transport recording the prompt."""

    def __init__(self):
        self.last_prompt = None

    def embed(self, texts):
        vecs = []
        for t in texts:
            u = t.upper()
            vecs.append([
                1.0 if "PAYROLL" in u else 0.0,
                1.0 if "TAXCALC" in u else 0.0,
                1.0 if "EMPLOYEE" in u or "EMPREC" in u else 0.0,
            ])
        return EmbeddingResponse(vectors=vecs, model="stub", provider="stub")

    def complete(self, task, request):
        from legacylens.llm.base import CompletionResponse

        self.last_prompt = request.messages[-1].content
        return CompletionResponse(
            text='{"purpose": "p", "business_logic": ["b"]}',
            model="stub",
            provider="stub",
        )


def _indexed(tmp_path) -> IndexStore:
    estate = tmp_path / "estate"
    shutil.copytree(FIXTURES / "cobol", estate)
    store = IndexStore(tmp_path / "index.db")
    Indexer(store, ["cobol"]).index(estate)
    return store


def test_context_provider_returns_related_excluding_self(tmp_path):
    store = _indexed(tmp_path)
    gw = StubGateway()
    Retriever(store, gw).build(["cobol"])  # build embeddings
    cp = ContextProvider(store, gw, k=2)
    assert cp.has_embeddings()

    payroll = next(a for a in store.list_artifacts("cobol") if a.rel_path.endswith("PAYROLL.cbl"))
    related = cp.related("payroll processing", exclude_rel=payroll.rel_path)
    store.close()
    assert all(rp != payroll.rel_path for rp, _ in related)
    assert related and all(isinstance(snip, str) and snip for _, snip in related)


def test_context_provider_graceful_without_embeddings(tmp_path):
    store = _indexed(tmp_path)  # no embeddings built
    cp = ContextProvider(store, StubGateway())
    assert cp.has_embeddings() is False
    assert cp.related("anything") == []
    store.close()


def test_doc_prompt_includes_related_context(tmp_path):
    store = _indexed(tmp_path)
    gw = StubGateway()
    Retriever(store, gw).build(["cobol"])
    graph = build_graph(store)
    payroll = next(a for a in store.list_artifacts("cobol") if a.rel_path.endswith("PAYROLL.cbl"))
    prog = CobolParser().parse(Path(payroll.abs_path).read_text(), kind="program").program

    cp = ContextProvider(store, gw, k=2)
    gen = DocGenerator(gateway=gw, context_provider=cp)
    md = gen.program_doc(prog, graph, payroll.rel_path, confidence=0.95)
    store.close()

    # The LLM prompt was augmented with a RELATED ARTIFACTS section.
    assert gw.last_prompt is not None
    assert "RELATED ARTIFACTS" in gw.last_prompt
    # and the generated doc used the (stub) LLM purpose.
    assert "_(inferred)_" in md


def test_doc_without_context_provider_has_no_related(tmp_path):
    store = _indexed(tmp_path)
    gw = StubGateway()
    graph = build_graph(store)
    payroll = next(a for a in store.list_artifacts("cobol") if a.rel_path.endswith("PAYROLL.cbl"))
    prog = CobolParser().parse(Path(payroll.abs_path).read_text(), kind="program").program
    DocGenerator(gateway=gw).program_doc(prog, graph, payroll.rel_path, confidence=0.95)
    store.close()
    assert "RELATED ARTIFACTS" not in (gw.last_prompt or "")
