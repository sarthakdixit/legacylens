"""ANTLR COBOL parser adapter.

Preprocesses source the same way the regex parser does (strip the sequence/indicator
area, drop comments, blank string literals), then feeds the cleaned, upper-cased code
to the generated ANTLR parser and walks the tree into the shared
:class:`~legacylens.parsing.model.CobolProgram` structure — so the rest of the
pipeline is identical regardless of backend.

Requires ``antlr4-python3-runtime`` and a generated parser under ``_generated/``.
Absent either, construction raises :class:`AntlrUnavailable` and the factory falls
back to the regex backend.
"""

from __future__ import annotations

from ..cobol import _PARAGRAPH_FALSE_POSITIVES, _detect_fixed_format, _normalize
from ..model import (
    CallStatement,
    CobolProgram,
    CopyStatement,
    DataItem,
    Paragraph,
    ParseResult,
)


class AntlrUnavailable(RuntimeError):
    """Raised when the ANTLR runtime or the generated parser is not available."""


def _preprocess(text: str) -> str:
    """Reduce source to clean code text: strip the sequence/indicator area and drop
    comment lines, then upper-case (the grammar is written in upper case). String
    literals are KEPT — the lexer's STRING token absorbs their contents, so keywords
    inside a message (e.g. 'GU CALL TO ROOT') never leak as statements."""
    fixed = _detect_fixed_format(text.splitlines())
    out = []
    for raw in text.splitlines():
        code = _normalize(raw, fixed)
        if code is not None:
            out.append(code)
    return "\n".join(out).upper()


class AntlrCobolParser:
    def __init__(self, gateway=None):
        try:
            from antlr4 import CommonTokenStream, InputStream, ParseTreeWalker
        except ImportError as exc:
            raise AntlrUnavailable(
                "antlr4-python3-runtime not installed (pip install 'legacylens[antlr]')"
            ) from exc
        try:
            from ._generated.CobolLexer import CobolLexer
            from ._generated.CobolListener import CobolListener
            from ._generated.CobolParser import CobolParser as _GenParser
        except Exception as exc:  # not generated yet
            raise AntlrUnavailable(
                "generated ANTLR COBOL parser not found; run `python scripts/build_antlr.py`"
            ) from exc

        self._InputStream = InputStream
        self._CommonTokenStream = CommonTokenStream
        self._ParseTreeWalker = ParseTreeWalker
        self._Lexer = CobolLexer
        self._Parser = _GenParser
        self._Listener = CobolListener
        self.gateway = gateway

    def parse(self, text: str, source_path: str | None = None, kind: str | None = None) -> ParseResult:
        cleaned = _preprocess(text)
        lexer = self._Lexer(self._InputStream(cleaned))
        tokens = self._CommonTokenStream(lexer)
        parser = self._Parser(tokens)
        parser.removeErrorListeners()  # tolerate messy legacy source
        tree = parser.program()

        program = CobolProgram(source_path=source_path)
        listener = _build_listener(self._Listener, program)
        self._ParseTreeWalker().walk(listener, tree)

        program.is_copybook = (kind == "copybook") or (
            program.program_id is None and "IDENTIFICATION" not in program.divisions
        )
        if program.is_copybook:
            confidence = 0.9 if program.data_items else 0.5
        elif program.program_id and program.paragraphs:
            confidence = 0.95
        elif program.program_id:
            confidence = 0.8
        else:
            confidence = 0.5
        return ParseResult(program=program, method="antlr", confidence=confidence)


def _text(node) -> str | None:
    try:
        return node.getText() if node is not None else None
    except Exception:  # pragma: no cover - defensive
        return None


def _line(ctx) -> int:
    try:
        return ctx.start.line
    except Exception:  # pragma: no cover
        return 0


def _build_listener(base, program: CobolProgram):
    """Create a listener (subclass of the generated base) that fills ``program``.

    Enter-method names follow ANTLR's convention for the rule names in Cobol.g4.
    """

    # Track the current division so paragraph labels are only accepted inside the
    # PROCEDURE DIVISION (the island grammar has no division context on its own).
    state = {"division": None}

    class _Listener(base):  # type: ignore[misc, valid-type]
        def enterProgramId(self, ctx):
            name = _text(ctx.NAME())
            if name and program.program_id is None:
                program.program_id = name.upper()
                program.program_id_source = "grammar"

        def enterDivision(self, ctx):
            name = (_text(ctx.divisionName()) or "").upper()
            state["division"] = name
            if name and name not in program.divisions:
                program.divisions.append(name)

        def enterCopyStmt(self, ctx):
            name = _text(ctx.NAME())
            if name:
                program.copies.append(CopyStatement(name=name.upper(), line=_line(ctx)))

        def enterCallStmt(self, ctx):
            literal = _text(ctx.STRING())
            if literal:
                program.calls.append(
                    CallStatement(target=literal.strip("'\"").upper(), line=_line(ctx), dynamic=False)
                )
            else:
                name = _text(ctx.NAME())
                if name:
                    program.calls.append(
                        CallStatement(target=name.upper(), line=_line(ctx), dynamic=True)
                    )

        def enterParagraph(self, ctx):
            name = _text(ctx.NAME())
            if not name:
                return
            upper = name.upper()
            # Paragraphs live in the PROCEDURE DIVISION; exclude verb labels
            # (EXIT./GOBACK./END-PERFORM.) that also parse as `NAME .`.
            if state["division"] != "PROCEDURE" or upper in _PARAGRAPH_FALSE_POSITIVES:
                return
            program.paragraphs.append(Paragraph(name=upper, line=_line(ctx)))

        def enterDataDescription(self, ctx):
            # Data items appear in the DATA DIVISION or a copybook fragment (no
            # division), never in PROCEDURE — matches the regex parser's scoping.
            if state["division"] == "PROCEDURE":
                return
            level = _text(ctx.LEVEL())
            name = _text(ctx.NAME())
            if level and name:
                # PICTURE extraction is a grammar enhancement; None for now.
                program.data_items.append(
                    DataItem(level=int(level), name=name.upper(), line=_line(ctx), pic=None)
                )

    return _Listener()
