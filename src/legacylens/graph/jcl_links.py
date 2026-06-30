"""Lightweight JCL link view for the dependency graph.

Delegates to the full :class:`~legacylens.parsing.jcl.JclParser` and exposes only the
job name, ``EXEC PGM=`` program invocations, and ``DD DSN=`` dataset references that
the graph builder consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..parsing.jcl import JclParser


@dataclass
class JclLinks:
    job_name: str | None = None
    programs: list[tuple[str, int]] = field(default_factory=list)
    datasets: list[tuple[str, int]] = field(default_factory=list)


def extract_jcl_links(text: str, fallback_name: str) -> JclLinks:
    job = JclParser().parse(text, fallback_name=fallback_name)
    return JclLinks(
        job_name=job.name,
        programs=job.programs(),
        datasets=job.datasets(),
    )
