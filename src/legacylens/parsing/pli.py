"""PL/I structural parser (line/regex-based, like the COBOL parser).

Extracts the program name (the ``OPTIONS(MAIN)`` procedure), nested procedures,
``CALL`` targets, and ``%INCLUDE`` members. Block comments (``/* ... */``) are
stripped per line. This is a v1 structural extractor — enough for graphing and
documentation — not a full PL/I grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
_PROC_RE = re.compile(r"\b([A-Z_][A-Z0-9_]*)\s*:\s*(?:PROC|PROCEDURE)\b(.*)", re.I)
_MAIN_RE = re.compile(r"OPTIONS\s*\(\s*MAIN\s*\)", re.I)
# Require a real boundary before CALL so suffixes don't match; targets are never
# string literals in PL/I, so literals are stripped before scanning (below).
_CALL_RE = re.compile(r"(?<![A-Z0-9_])CALL\s+([A-Z_][A-Z0-9_]*)", re.I)
_INCLUDE_RE = re.compile(r"%INCLUDE\s+\(?\s*([A-Z_][A-Z0-9_]*)", re.I)
_DECLARE_RE = re.compile(r"\b(?:DECLARE|DCL)\b", re.I)


@dataclass
class PliProcedure:
    name: str
    line: int
    is_main: bool = False


@dataclass
class PliProgram:
    name: str | None = None
    procedures: list[PliProcedure] = field(default_factory=list)
    calls: list[tuple[str, int]] = field(default_factory=list)
    includes: list[tuple[str, int]] = field(default_factory=list)
    declare_count: int = 0
    source_path: str | None = None


class PliParser:
    def parse(self, text: str, source_path: str | None = None, fallback_name: str = "") -> PliProgram:
        prog = PliProgram(source_path=source_path)
        # Strip block comments, then blank string-literal contents so CALL/identifiers
        # inside text (e.g. PUT LIST('CALL THE PROC')) are not mistaken for statements.
        clean = _COMMENT_RE.sub(" ", text)
        scan = _STRING_LITERAL.sub("''", clean)

        # Procedures: the label and PROCEDURE/PROC keyword may sit on separate lines
        # (`run_inner_proc:` \n `proc;`), so match across the whole (comment-stripped)
        # text — `\s*` spans newlines — and derive the line from the match offset.
        for m in _PROC_RE.finditer(scan):
            idx = scan.count("\n", 0, m.start()) + 1
            is_main = bool(_MAIN_RE.search(m.group(2)))
            proc = PliProcedure(name=m.group(1).upper(), line=idx, is_main=is_main)
            prog.procedures.append(proc)
            if is_main and prog.name is None:
                prog.name = proc.name

        for idx, line in enumerate(scan.splitlines(), start=1):
            for m in _CALL_RE.finditer(line):
                prog.calls.append((m.group(1).upper(), idx))
            for m in _INCLUDE_RE.finditer(line):
                prog.includes.append((m.group(1).upper(), idx))
            prog.declare_count += len(_DECLARE_RE.findall(line))

        if prog.name is None:
            prog.name = (prog.procedures[0].name if prog.procedures else fallback_name.upper()) or None
        return prog
