"""Artifact classification.

Mainframe source frequently arrives without file extensions (PDS members), so
classification is two-stage:

1. **Extension map** — fast and unambiguous when present.
2. **Content heuristics** — scan the first lines for tell-tale markers
   (``IDENTIFICATION DIVISION`` for COBOL, ``//`` job cards for JCL, ``PROC ...
   OPTIONS`` for PL/I) when the extension is unknown.

``classify`` returns ``None`` for the language when a file looks like neither
supported source nor an obvious binary — callers treat that as "unknown / skip".
"""

from __future__ import annotations

from dataclasses import dataclass

# Languages
COBOL = "cobol"
JCL = "jcl"
PLI = "pli"

# Kinds
PROGRAM = "program"
COPYBOOK = "copybook"
JOB = "job"
INCLUDE = "include"

_EXTENSION_MAP: dict[str, tuple[str, str]] = {
    # COBOL
    ".cbl": (COBOL, PROGRAM),
    ".cob": (COBOL, PROGRAM),
    ".cobol": (COBOL, PROGRAM),
    ".cpy": (COBOL, COPYBOOK),
    ".copy": (COBOL, COPYBOOK),
    # JCL
    ".jcl": (JCL, JOB),
    ".job": (JCL, JOB),
    ".jcs": (JCL, JOB),
    # PL/I
    ".pli": (PLI, PROGRAM),
    ".pl1": (PLI, PROGRAM),
    ".inc": (PLI, INCLUDE),
}


@dataclass
class Classification:
    language: str | None
    kind: str
    # How the decision was reached: "extension" | "content" | "unknown".
    method: str


def _looks_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _classify_by_content(text: str) -> Classification | None:
    upper = text.upper()
    head = "\n".join(text.splitlines()[:200])
    head_upper = upper[: len(head)] if head else upper

    # JCL: statements begin with // and reference JOB/EXEC/DD.
    nonblank = [ln for ln in text.splitlines() if ln.strip()]
    if nonblank:
        slash_lines = sum(1 for ln in nonblank[:50] if ln.startswith("//"))
        if slash_lines and any(tok in head_upper for tok in (" JOB", " EXEC", " DD ", "EXEC PGM")):
            return Classification(JCL, JOB, "content")

    # COBOL: the IDENTIFICATION DIVISION / PROGRAM-ID is unmistakable.
    if "IDENTIFICATION DIVISION" in upper or "PROGRAM-ID" in upper:
        return Classification(COBOL, PROGRAM, "content")

    # PL/I: a procedure with OPTIONS(MAIN) or OPTIONS (MAIN).
    if "PROCEDURE OPTIONS" in upper or "PROC OPTIONS" in upper or "OPTIONS(MAIN)" in upper.replace(" ", ""):
        return Classification(PLI, PROGRAM, "content")

    return None


def classify(filename: str, sample_bytes: bytes) -> Classification:
    """Classify a file from its name and a sample of its bytes.

    ``sample_bytes`` should be the file's leading bytes (a few KB is plenty); only
    a prefix is examined so this stays cheap on large estates.
    """
    dot = filename.rfind(".")
    ext = filename[dot:].lower() if dot != -1 else ""
    if ext in _EXTENSION_MAP:
        language, kind = _EXTENSION_MAP[ext]
        return Classification(language, kind, "extension")

    if _looks_binary(sample_bytes):
        return Classification(None, "unknown", "unknown")

    try:
        text = sample_bytes.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decode with replace shouldn't raise
        return Classification(None, "unknown", "unknown")

    result = _classify_by_content(text)
    return result or Classification(None, "unknown", "unknown")
