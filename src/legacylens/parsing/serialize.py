"""(De)serialize parse results for the persistent parse cache.

CobolProgram and its nested value objects are plain dataclasses, so ``asdict`` gives
a JSON-safe dict; reconstruction rebuilds the nested dataclasses explicitly.
"""

from __future__ import annotations

from dataclasses import asdict

from .model import (
    CallStatement,
    CobolProgram,
    CopyStatement,
    DataItem,
    Paragraph,
    ParseResult,
    Section,
    SqlTableRef,
)


def parseresult_to_dict(result: ParseResult) -> dict:
    return {
        "program": asdict(result.program),
        "method": result.method,
        "confidence": result.confidence,
        "warnings": list(result.warnings),
    }


def _program_from_dict(d: dict, source_path: str | None) -> CobolProgram:
    return CobolProgram(
        program_id=d.get("program_id"),
        is_copybook=d.get("is_copybook", False),
        program_id_source=d.get("program_id_source"),
        divisions=list(d.get("divisions", [])),
        sections=[Section(**s) for s in d.get("sections", [])],
        paragraphs=[Paragraph(**p) for p in d.get("paragraphs", [])],
        data_items=[DataItem(**x) for x in d.get("data_items", [])],
        copies=[CopyStatement(**c) for c in d.get("copies", [])],
        calls=[CallStatement(**c) for c in d.get("calls", [])],
        sql_tables=[SqlTableRef(**t) for t in d.get("sql_tables", [])],
        # The cache is content-addressed, so override with the caller's path.
        source_path=source_path,
    )


def parseresult_from_dict(d: dict, source_path: str | None = None) -> ParseResult:
    return ParseResult(
        program=_program_from_dict(d["program"], source_path),
        method=d.get("method", "grammar"),
        confidence=d.get("confidence", 1.0),
        warnings=list(d.get("warnings", [])),
    )
