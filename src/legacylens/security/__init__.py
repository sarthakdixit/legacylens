"""Security & compliance analysis.

Two complementary sources of findings, kept clearly distinct:

* **Deterministic rule packs** (``security.rules``) — pattern/structure rules mapped
  to CWE/OWASP. Reproducible and authoritative; ``requires_human_review = False``.
* **LLM-assisted analysis** (``security.analyzer``) — advisory findings from the
  configured model. Always ``source = "llm"`` and ``requires_human_review = True``,
  honoring the requirement that LLM-inferred findings are advisory until a human
  confirms them.

Findings are emitted as SARIF/JSON (machine-readable) and HTML (audit report).
"""

from .analyzer import SecurityAnalyzer
from .emit import to_html, to_json, to_sarif
from .model import Finding, Severity

__all__ = ["SecurityAnalyzer", "Finding", "Severity", "to_sarif", "to_json", "to_html"]
