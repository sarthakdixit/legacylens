"""Tests for client-selectable COBOL parser backend (regex / antlr)."""

from __future__ import annotations

import pytest

from legacylens.config import Config, ParserBackend
from legacylens.parsing import CobolParser, build_cobol_parser
from legacylens.parsing.antlr.backend import AntlrUnavailable

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def _antlr_built() -> bool:
    """True only when the ANTLR runtime AND generated parser are both present."""
    try:
        from legacylens.parsing.antlr.backend import AntlrCobolParser

        AntlrCobolParser()
        return True
    except Exception:
        return False


ANTLR_BUILT = _antlr_built()


def test_config_defaults_to_regex_backend():
    cfg = Config.model_validate(
        {
            "version": 1,
            "project": {"name": "t"},
            "languages": ["cobol"],
            "llm": {"providers": [{"name": "l", "type": "local", "model": "m"}], "routing": {"default": "l"}},
        }
    )
    assert cfg.parser.backend is ParserBackend.regex
    assert cfg.parser.fallback_to_regex is True


def test_config_accepts_antlr_backend():
    cfg = Config.model_validate(
        {
            "version": 1,
            "project": {"name": "t"},
            "languages": ["cobol"],
            "llm": {"providers": [{"name": "l", "type": "local", "model": "m"}], "routing": {"default": "l"}},
            "parser": {"backend": "antlr", "fallback_to_regex": False},
        }
    )
    assert cfg.parser.backend is ParserBackend.antlr
    assert cfg.parser.fallback_to_regex is False


def test_factory_returns_regex_by_default():
    parser = build_cobol_parser("regex")
    assert isinstance(parser, CobolParser)


@pytest.mark.skipif(ANTLR_BUILT, reason="ANTLR is built here; fallback path not exercised")
def test_factory_antlr_falls_back_to_regex_when_unavailable():
    parser = build_cobol_parser("antlr", fallback_to_regex=True)
    assert isinstance(parser, CobolParser)


@pytest.mark.skipif(ANTLR_BUILT, reason="ANTLR is built here; unavailability path not exercised")
def test_factory_antlr_raises_when_fallback_disabled():
    with pytest.raises(AntlrUnavailable):
        build_cobol_parser("antlr", fallback_to_regex=False)


def test_selected_backend_produces_same_interface():
    # Whichever backend the factory returns (regex or antlr), the contract holds.
    parser = build_cobol_parser("antlr", fallback_to_regex=True)
    result = parser.parse((FIXTURES / "cobol" / "PAYROLL.cbl").read_text(), kind="program")
    assert result.program.program_id == "PAYROLL"


@pytest.mark.skipif(not ANTLR_BUILT, reason="ANTLR not generated (run scripts/build_antlr.py)")
def test_antlr_backend_parses_when_built():
    from legacylens.parsing.antlr.backend import AntlrCobolParser

    result = AntlrCobolParser().parse(
        (FIXTURES / "cobol" / "PAYROLL.cbl").read_text(), kind="program"
    )
    assert result.method == "antlr"
    assert result.program.program_id == "PAYROLL"
    assert {p.name for p in result.program.paragraphs} == {"MAIN-PARA", "INIT-PARA", "WRITE-PARA"}
    assert any(c.target == "TAXCALC" and not c.dynamic for c in result.program.calls)
    assert any(c.name == "EMPREC" for c in result.program.copies)
