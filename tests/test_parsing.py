"""Tests for the COBOL structural parser (B3 gate)."""

from __future__ import annotations

from pathlib import Path

from legacylens.config import Config
from legacylens.llm import build_gateway
from legacylens.parsing import CobolParser

FIXTURES = Path(__file__).parent / "fixtures"


def _read(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


def test_parses_program_structure():
    result = CobolParser().parse(_read("cobol/PAYROLL.cbl"), kind="program")
    prog = result.program
    assert prog.program_id == "PAYROLL"
    assert prog.program_id_source == "grammar"
    assert not prog.is_copybook
    assert set(prog.divisions) == {"IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"}
    para_names = {p.name for p in prog.paragraphs}
    assert {"MAIN-PARA", "INIT-PARA", "WRITE-PARA"} <= para_names
    assert result.confidence >= 0.9
    assert result.method == "grammar"


def test_extracts_calls_and_copies():
    prog = CobolParser().parse(_read("cobol/PAYROLL.cbl"), kind="program").program
    assert any(c.name == "EMPREC" for c in prog.copies)
    call_targets = {c.target for c in prog.calls}
    assert "TAXCALC" in call_targets
    taxcalc = next(c for c in prog.calls if c.target == "TAXCALC")
    assert taxcalc.dynamic is False  # CALL 'TAXCALC' is a static literal


def test_extracts_data_items_with_pic():
    prog = CobolParser().parse(_read("cobol/PAYROLL.cbl"), kind="program").program
    total = next(d for d in prog.data_items if d.name == "WS-TOTAL")
    assert total.level == 1
    assert total.pic == "9(7)V99"


def test_copybook_is_recognized():
    result = CobolParser().parse(_read("cobol/EMPREC.cpy"), kind="copybook")
    prog = result.program
    assert prog.is_copybook
    assert prog.program_id is None
    names = {d.name for d in prog.data_items}
    assert {"EMPLOYEE-RECORD", "EMP-ID", "EMP-NAME", "EMP-SALARY"} <= names


def test_copybook_detected_without_kind_hint():
    # No kind passed; absence of IDENTIFICATION DIVISION implies a copybook.
    result = CobolParser().parse(_read("cobol/EMPREC.cpy"))
    assert result.program.is_copybook


def test_dynamic_call_detected():
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. DYN.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           CALL WS-PROG-NAME.\n"
    )
    prog = CobolParser().parse(src, kind="program").program
    call = next(c for c in prog.calls if c.target == "WS-PROG-NAME")
    assert call.dynamic is True


def test_call_inside_string_literal_is_ignored():
    # Real-world false positive from AWS CardDemo: 'CALL TO' inside a DISPLAY string.
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MSGS.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           DISPLAY 'GU CALL TO ROOT SEG SUCCESS'.\n"
        "           DISPLAY 'ROOT GU CALL FAIL:' WS-STATUS.\n"
    )
    prog = CobolParser().parse(src, kind="program").program
    assert prog.calls == []  # no phantom calls to TO / FAIL


def test_call_suffix_of_hyphenated_name_is_ignored():
    # `INSERT-IMS-CALL THRU` must not be read as `CALL THRU`.
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PERF.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           PERFORM 3200-INSERT-IMS-CALL THRU 3200-EXIT.\n"
    )
    prog = CobolParser().parse(src, kind="program").program
    assert all(c.target != "THRU" for c in prog.calls)


def test_comments_are_ignored():
    src = (
        "      * THIS IS A COMMENT WITH CALL 'GHOST'\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CMT.\n"
    )
    prog = CobolParser().parse(src, kind="program").program
    assert prog.program_id == "CMT"
    assert all(c.target != "GHOST" for c in prog.calls)


def test_low_confidence_without_program_id():
    # Looks like a program (kind hint) but has no PROGRAM-ID and no IDENTIFICATION.
    src = "       PROCEDURE DIVISION.\n           DISPLAY 'HI'.\n"
    result = CobolParser().parse(src, kind="program")
    assert result.confidence < 0.5


# --------------------------------------------------------------------------- #
# LLM fallback
# --------------------------------------------------------------------------- #
class FakeTransport:
    def post_json(self, url, headers, payload, timeout=60.0):
        return {
            "model": payload.get("model", "m"),
            "choices": [
                {"message": {"content": '{"program_id": "RECOVERED", "paragraphs": ["P1"], "calls": ["SUBX"]}'}}
            ],
        }


def _gateway():
    cfg = Config.model_validate(
        {
            "version": 1,
            "project": {"name": "t"},
            "languages": ["cobol"],
            "llm": {
                "providers": [{"name": "local", "type": "local", "model": "m", "base_url": "http://localhost:1/v1"}],
                "routing": {"default": "local"},
            },
        }
    )
    return build_gateway(cfg, transport=FakeTransport(), use_cache=False)


def test_llm_fallback_recovers_structure():
    src = "       PROCEDURE DIVISION.\n           DISPLAY 'HI'.\n"  # no PROGRAM-ID
    result = CobolParser(gateway=_gateway()).parse(src, kind="program")
    assert result.method == "grammar+llm"
    assert result.program.program_id == "RECOVERED"
    assert result.program.program_id_source == "llm"
    assert any(p.inferred for p in result.program.paragraphs)
    assert any(c.inferred and c.target == "SUBX" for c in result.program.calls)


def test_no_fallback_when_grammar_is_confident():
    # A clean program must NOT trigger the LLM even if a gateway is present.
    calls = {"n": 0}

    class CountingTransport:
        def post_json(self, *a, **k):
            calls["n"] += 1
            return {"choices": [{"message": {"content": "{}"}}]}

    cfg = Config.model_validate(
        {
            "version": 1,
            "project": {"name": "t"},
            "languages": ["cobol"],
            "llm": {
                "providers": [{"name": "local", "type": "local", "model": "m", "base_url": "http://localhost:1/v1"}],
                "routing": {"default": "local"},
            },
        }
    )
    gw = build_gateway(cfg, transport=CountingTransport(), use_cache=False)
    result = CobolParser(gateway=gw).parse(_read("cobol/PAYROLL.cbl"), kind="program")
    assert result.method == "grammar"
    assert calls["n"] == 0
