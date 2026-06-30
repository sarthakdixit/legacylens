"""JCL structural parser.

Builds a job/step/DD model, handling JCL continuation lines (a statement continues
when the next line has a blank name field, i.e. ``//`` followed by whitespace). This
is the full parser; :mod:`legacylens.graph.jcl_links` delegates to it for the lighter
link-only view the graph needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NAME_STMT = re.compile(r"^//(\S+)\s+(JOB|EXEC|DD)\b\s*(.*)$", re.I)
_PGM_RE = re.compile(r"\bPGM=([A-Z0-9#@$]+)", re.I)
_PROC_RE = re.compile(r"\bPROC=([A-Z0-9#@$]+)", re.I)
_DSN_RE = re.compile(r"\bDSN(?:AME)?=([A-Z0-9.$#@-]+)", re.I)
_DISP_RE = re.compile(r"\bDISP=(\([^)]*\)|[A-Z]+)", re.I)


@dataclass
class JclDD:
    name: str
    line: int
    dsn: str | None = None
    disp: str | None = None


@dataclass
class JclStep:
    name: str
    line: int
    pgm: str | None = None
    proc: str | None = None
    dds: list[JclDD] = field(default_factory=list)


@dataclass
class JclJob:
    name: str | None = None
    line: int = 0
    steps: list[JclStep] = field(default_factory=list)

    def programs(self) -> list[tuple[str, int]]:
        return [(s.pgm, s.line) for s in self.steps if s.pgm]

    def datasets(self) -> list[tuple[str, int]]:
        return [(dd.dsn, dd.line) for s in self.steps for dd in s.dds if dd.dsn]


def _logical_statements(text: str):
    """Yield (line_number, merged_statement) joining JCL continuations."""
    current: str | None = None
    current_line = 0
    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n")
        if line.startswith("//*") or not line.startswith("//"):
            continue
        after = line[2:]
        is_continuation = after[:1].isspace() or after.strip() == ""
        if is_continuation and current is not None:
            current += " " + after.strip()
            continue
        if current is not None:
            yield current_line, current
        current = line
        current_line = idx
    if current is not None:
        yield current_line, current


class JclParser:
    def parse(self, text: str, fallback_name: str = "") -> JclJob:
        job = JclJob()
        current_step: JclStep | None = None

        for line_no, stmt in _logical_statements(text):
            m = _NAME_STMT.match(stmt)
            if not m:
                continue
            name, verb, rest = m.group(1).upper(), m.group(2).upper(), m.group(3)

            if verb == "JOB":
                job.name = name
                job.line = line_no
            elif verb == "EXEC":
                pgm = _PGM_RE.search(rest)
                proc = _PROC_RE.search(rest)
                # `EXEC PROCNAME` (positional proc) when no PGM=/PROC= keyword.
                positional = None
                if not pgm and not proc:
                    first = rest.strip().split(",", 1)[0].strip()
                    if first and "=" not in first:
                        positional = first.upper()
                current_step = JclStep(
                    name=name,
                    line=line_no,
                    pgm=pgm.group(1).upper() if pgm else None,
                    proc=(proc.group(1).upper() if proc else positional),
                )
                job.steps.append(current_step)
            elif verb == "DD" and current_step is not None:
                dsn = _DSN_RE.search(rest)
                disp = _DISP_RE.search(rest)
                current_step.dds.append(
                    JclDD(
                        name=name,
                        line=line_no,
                        dsn=dsn.group(1).upper() if dsn else None,
                        disp=disp.group(1) if disp else None,
                    )
                )

        if job.name is None and fallback_name:
            job.name = fallback_name.upper()
        return job
