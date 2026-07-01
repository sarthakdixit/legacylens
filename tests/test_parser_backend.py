"""Tests for client-selectable COBOL parser backend (regex / antlr)."""

from __future__ import annotations

import importlib.util

import pytest

from legacylens.config import Config, ParserBackend
from legacylens.parsing import CobolParser, build_cobol_parser
from legacylens.parsing.antlr.backend import AntlrUnavailable

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"

_ANTLR_AVAILABLE = importlib.util.find_spec("antlr4") is not None


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


def test_factory_antlr_falls_back_to_regex_when_unavailable():
    # ANTLR parser is not generated in this environment → graceful fallback.
    parser = build_cobol_parser("antlr", fallback_to_regex=True)
    assert isinstance(parser, CobolParser)


def test_factory_antlr_raises_when_fallback_disabled():
    if _ANTLR_AVAILABLE and importlib.util.find_spec("legacylens.parsing.antlr._generated") is not None:
        pytest.skip("ANTLR parser is generated; unavailability path not exercised here")
    with pytest.raises(AntlrUnavailable):
        build_cobol_parser("antlr", fallback_to_regex=False)


def test_regex_and_selected_backend_produce_same_interface():
    # Whichever backend the factory returns, it must satisfy the parse() contract.
    parser = build_cobol_parser("antlr", fallback_to_regex=True)  # regex here
    result = parser.parse((FIXTURES / "cobol" / "PAYROLL.cbl").read_text(), kind="program")
    assert result.program.program_id == "PAYROLL"


@pytest.mark.skipif(
    not (_ANTLR_AVAILABLE and importlib.util.find_spec("legacylens.parsing.antlr._generated")),
    reason="ANTLR runtime + generated parser not present (run scripts/build_antlr.py)",
)
def test_antlr_backend_parses_when_built():
    from legacylens.parsing.antlr.backend import AntlrCobolParser

    parser = AntlrCobolParser()
    result = parser.parse((FIXTURES / "cobol" / "PAYROLL.cbl").read_text(), kind="program")
    assert result.method == "antlr"
    assert result.program.program_id == "PAYROLL"
    assert any(c.target == "TAXCALC" for c in result.program.calls)
    assert any(c.name == "EMPREC" for c in result.program.copies)
