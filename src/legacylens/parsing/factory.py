"""COBOL parser backend selection.

Two backends implement the same interface (``parse(text, source_path, kind) ->
ParseResult``):

* ``regex`` — the default pure-Python, zero-dependency line parser.
* ``antlr`` — an ANTLR grammar-based parser (higher fidelity). It requires the
  ANTLR runtime plus a *generated* parser (a one-time ``scripts/build_antlr.py``
  step that needs Java). When it is not available, the factory falls back to the
  regex backend unless the client opts out (``fallback_to_regex: false``).

Client choice is expressed in config under ``parser.backend``.
"""

from __future__ import annotations

from ..logging_setup import get_logger
from .cobol import CobolParser

log = get_logger()


def build_cobol_parser(backend: str = "regex", gateway=None, fallback_to_regex: bool = True):
    """Return a COBOL parser for the requested backend.

    ``backend`` is the string value of ``config.parser.backend`` ("regex"/"antlr").
    """
    if backend == "antlr":
        try:
            from .antlr.backend import AntlrCobolParser

            parser = AntlrCobolParser(gateway=gateway)
            log.info("Using ANTLR COBOL parser backend.")
            return parser
        except Exception as exc:  # AntlrUnavailable, ImportError, etc.
            if fallback_to_regex:
                log.warning(
                    "ANTLR parser backend unavailable (%s); falling back to the regex parser.",
                    exc,
                )
                return CobolParser(gateway=gateway)
            raise
    return CobolParser(gateway=gateway)
