"""ANTLR-based COBOL parser backend (optional, opt-in).

This package is inert until the client generates the parser from the grammar
(`Cobol.g4`) with `scripts/build_antlr.py` — which needs Java once, at build time.
The generated Python sources land in `_generated/` here; at runtime only the pure-
Python `antlr4-python3-runtime` is required (installable via the `antlr` extra).

If nothing is generated, importing :class:`~legacylens.parsing.antlr.backend.AntlrCobolParser`
raises :class:`~legacylens.parsing.antlr.backend.AntlrUnavailable`, and the parser
factory falls back to the regex backend.
"""
