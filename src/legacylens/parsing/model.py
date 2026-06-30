"""Structural model produced by the parsers.

These are deliberately language-light value objects: enough structure for dependency
graphing (B4), security analysis (B5), and documentation (B6) without trying to be a
full AST. Each element carries its 1-based source ``line`` so findings and docs can
cite locations, and an ``inferred`` flag distinguishing grammar-derived facts from
LLM-supplied ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    name: str
    line: int


@dataclass
class Paragraph:
    name: str
    line: int
    section: str | None = None
    inferred: bool = False


@dataclass
class DataItem:
    level: int
    name: str
    line: int
    pic: str | None = None


@dataclass
class CopyStatement:
    name: str
    line: int


@dataclass
class CallStatement:
    target: str
    line: int
    # Dynamic calls reference a variable holding the program name; the concrete
    # target is not statically known.
    dynamic: bool = False
    inferred: bool = False


@dataclass
class CobolProgram:
    program_id: str | None = None
    is_copybook: bool = False
    # How program_id was determined: "grammar" | "llm" | None.
    program_id_source: str | None = None
    divisions: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    data_items: list[DataItem] = field(default_factory=list)
    copies: list[CopyStatement] = field(default_factory=list)
    calls: list[CallStatement] = field(default_factory=list)
    source_path: str | None = None


@dataclass
class ParseResult:
    program: CobolProgram
    # "grammar" when fully grammar-derived; "grammar+llm" when the fallback ran.
    method: str = "grammar"
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
