"""Source parsing into structural models.

v1 ships a pure-Python, line/regex-based COBOL parser (no JVM dependency, trivial to
install air-gapped). It extracts the structure later stages need — program id,
divisions, sections, paragraphs, data items, ``COPY`` includes and ``CALL`` targets —
and exposes an LLM-fallback hook (via the B1 gateway) for inputs the grammar cannot
confidently handle. Anything the LLM supplies is labelled ``inferred`` so it never
silently becomes authoritative.
"""

from .cobol import CobolParser
from .factory import build_cobol_parser
from .jcl import JclDD, JclJob, JclParser, JclStep
from .model import (
    CallStatement,
    CobolProgram,
    CopyStatement,
    DataItem,
    Paragraph,
    ParseResult,
    Section,
)
from .pli import PliParser, PliProcedure, PliProgram

__all__ = [
    "CobolParser",
    "build_cobol_parser",
    "ParseResult",
    "CobolProgram",
    "Paragraph",
    "Section",
    "DataItem",
    "CopyStatement",
    "CallStatement",
    "JclParser",
    "JclJob",
    "JclStep",
    "JclDD",
    "PliParser",
    "PliProgram",
    "PliProcedure",
]
