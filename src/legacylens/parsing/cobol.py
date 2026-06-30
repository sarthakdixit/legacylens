"""Line/regex-based COBOL structural parser.

Handles both fixed-format source (sequence numbers in cols 1-6, indicator in col 7,
code in cols 8-72) and free-format source, detected per file. It is intentionally
tolerant: it extracts the structural facts downstream stages need and records
warnings rather than failing on constructs it doesn't model.

When grammar confidence is low (e.g. a program with no discoverable ``PROGRAM-ID``)
and a gateway is available, :meth:`CobolParser.parse` asks the LLM to recover the
missing structure; those results are flagged ``inferred``.
"""

from __future__ import annotations

import json
import re

from ..logging_setup import get_logger
from .model import (
    CallStatement,
    CobolProgram,
    CopyStatement,
    DataItem,
    Paragraph,
    ParseResult,
    Section,
)

log = get_logger()

_DIVISION_RE = re.compile(r"^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\b\.?\s*([A-Z0-9][A-Z0-9-]*)", re.I)
_SECTION_RE = re.compile(r"^\s*([A-Z0-9][A-Z0-9-]*)\s+SECTION\s*\.", re.I)
_PARAGRAPH_RE = re.compile(r"^\s*([A-Z0-9][A-Z0-9-]*)\s*\.\s*$", re.I)
_COPY_RE = re.compile(r"\bCOPY\s+([A-Z0-9][A-Z0-9-]*)", re.I)
_CALL_RE = re.compile(r"""\bCALL\s+(?:'([^']+)'|"([^"]+)"|([A-Z0-9][A-Z0-9-]*))""", re.I)
_DATA_ITEM_RE = re.compile(r"^\s*(\d{1,2})\s+(FILLER|[A-Z0-9][A-Z0-9-]*)\b(.*)$", re.I)
_PIC_RE = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?([^\s.]+)", re.I)

# Tokens that look like a paragraph (single word + period) but are really verbs.
_PARAGRAPH_FALSE_POSITIVES = {"STOP", "EXIT", "CONTINUE", "GOBACK", "END-IF", "END-PERFORM"}


def _detect_fixed_format(lines: list[str]) -> bool:
    """Heuristic: fixed-format source keeps cols 1-6 blank or numeric."""
    sampled = considered = 0
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        considered += 1
        seq = line[:6]
        if len(line) >= 7 and (seq.isspace() or seq.strip().isdigit() or seq == ""):
            sampled += 1
        if considered >= 60:
            break
    if considered == 0:
        return True
    return sampled / considered >= 0.7


def _normalize(raw: str, fixed: bool) -> str | None:
    """Return the code portion of a line, or None if it is a comment/blank."""
    line = raw.rstrip("\r\n")
    if fixed:
        if len(line) >= 7 and line[6] in ("*", "/"):
            return None
        code = line[7:72] if len(line) > 7 else ""
    else:
        stripped = line.lstrip()
        if stripped.startswith("*"):
            return None
        code = line.split("*>", 1)[0]  # inline free-format comment
    code = code.rstrip()
    return code if code.strip() else None


class CobolParser:
    def __init__(self, gateway=None):
        self.gateway = gateway

    def parse(self, text: str, source_path: str | None = None, kind: str | None = None) -> ParseResult:
        raw_lines = text.splitlines()
        fixed = _detect_fixed_format(raw_lines)
        program = CobolProgram(source_path=source_path)
        warnings: list[str] = []
        current_division: str | None = None
        current_section: str | None = None

        for idx, raw in enumerate(raw_lines, start=1):
            code = _normalize(raw, fixed)
            if code is None:
                continue

            div = _DIVISION_RE.match(code)
            if div:
                name = div.group(1).upper()
                name = "IDENTIFICATION" if name == "ID" else name
                current_division = name
                current_section = None
                if name not in program.divisions:
                    program.divisions.append(name)
                continue

            pid = _PROGRAM_ID_RE.match(code)
            if pid and program.program_id is None:
                program.program_id = pid.group(1).upper()
                program.program_id_source = "grammar"
                continue

            # COPY and CALL can occur on data or procedure lines.
            for m in _COPY_RE.finditer(code):
                program.copies.append(CopyStatement(name=m.group(1).upper(), line=idx))
            for m in _CALL_RE.finditer(code):
                literal = m.group(1) or m.group(2)
                if literal:
                    program.calls.append(CallStatement(target=literal.upper(), line=idx, dynamic=False))
                else:
                    program.calls.append(CallStatement(target=m.group(3).upper(), line=idx, dynamic=True))

            sec = _SECTION_RE.match(code)
            if sec:
                current_section = sec.group(1).upper()
                program.sections.append(Section(name=current_section, line=idx))
                continue

            # Data items appear in the DATA DIVISION of a program, or bare in a
            # copybook fragment (which has no division header at all).
            if current_division != "PROCEDURE":
                item = _DATA_ITEM_RE.match(code)
                if item:
                    pic_m = _PIC_RE.search(item.group(3))
                    program.data_items.append(
                        DataItem(
                            level=int(item.group(1)),
                            name=item.group(2).upper(),
                            line=idx,
                            pic=pic_m.group(1) if pic_m else None,
                        )
                    )
                    continue

            if current_division == "PROCEDURE":
                para = _PARAGRAPH_RE.match(code)
                if para and para.group(1).upper() not in _PARAGRAPH_FALSE_POSITIVES:
                    program.paragraphs.append(
                        Paragraph(name=para.group(1).upper(), line=idx, section=current_section)
                    )

        program.is_copybook = self._is_copybook(program, kind)
        confidence = self._confidence(program, warnings)
        method = "grammar"

        if confidence < 0.5 and self.gateway is not None and not program.is_copybook:
            if self._llm_fallback(text, program, warnings):
                method = "grammar+llm"
                confidence = self._confidence(program, warnings)

        return ParseResult(program=program, method=method, confidence=confidence, warnings=warnings)

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _is_copybook(program: CobolProgram, kind: str | None) -> bool:
        # An explicit classification (from ingestion) is authoritative.
        if kind == "copybook":
            return True
        if kind == "program":
            return False
        # No hint: a fragment without an IDENTIFICATION DIVISION / PROGRAM-ID is a copybook.
        return program.program_id is None and "IDENTIFICATION" not in program.divisions

    @staticmethod
    def _confidence(program: CobolProgram, warnings: list[str]) -> float:
        if program.is_copybook:
            return 0.9 if program.data_items else 0.5
        if program.program_id and program.paragraphs:
            return 0.95
        if program.program_id:
            return 0.8
        warnings.append("no PROGRAM-ID found in a non-copybook source")
        return 0.3

    def _llm_fallback(self, text: str, program: CobolProgram, warnings: list[str]) -> bool:
        """Ask the LLM to recover structure the grammar missed. Returns True if it
        contributed anything. All additions are flagged ``inferred``."""
        from ..llm import CompletionRequest, Message  # local import to avoid cycle

        prompt = (
            "You are analyzing a COBOL source file whose structure could not be parsed "
            "deterministically. Return ONLY a JSON object with keys: "
            '"program_id" (string or null), "paragraphs" (array of strings), '
            '"calls" (array of strings). No prose.\n\n'
            f"SOURCE:\n{text[:6000]}"
        )
        try:
            resp = self.gateway.complete(
                "parse_fallback",
                CompletionRequest(messages=[Message(role="user", content=prompt)]),
            )
            data = _extract_json(resp.text)
        except Exception as exc:  # never let the fallback crash a run
            warnings.append(f"LLM fallback failed: {exc}")
            return False

        contributed = False
        if not program.program_id and isinstance(data.get("program_id"), str):
            program.program_id = data["program_id"].upper()
            program.program_id_source = "llm"
            contributed = True
        for name in data.get("paragraphs", []) or []:
            if isinstance(name, str):
                program.paragraphs.append(Paragraph(name=name.upper(), line=0, inferred=True))
                contributed = True
        for target in data.get("calls", []) or []:
            if isinstance(target, str):
                program.calls.append(CallStatement(target=target.upper(), line=0, inferred=True))
                contributed = True
        if contributed:
            warnings.append("structure partially recovered by LLM (flagged inferred)")
        return contributed


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response (tolerates code fences)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])
