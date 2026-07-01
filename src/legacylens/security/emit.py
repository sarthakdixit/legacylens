"""Emitters for security findings: SARIF, native JSON, and an HTML report."""

from __future__ import annotations

import json
from html import escape

from .. import __version__
from .model import Finding, SEVERITY_RANK

# SARIF severity → level mapping.
_SARIF_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}

_HTML_SEVERITY_COLOR = {
    "critical": "#7d1128",
    "high": "#c1121f",
    "medium": "#e09f3e",
    "low": "#2a9d8f",
    "info": "#577590",
}


def summarize(findings: list[Finding]) -> dict:
    by_severity: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_source[f.source] = by_source.get(f.source, 0) + 1
    return {
        "total": len(findings),
        "by_severity": by_severity,
        "by_source": by_source,
        "requires_human_review": sum(1 for f in findings if f.requires_human_review),
        "suppressed": sum(1 for f in findings if f.suppressed),
    }


def to_json(findings: list[Finding]) -> str:
    def _row(f: Finding) -> dict:
        d = f.to_dict()
        d["fingerprint"] = f.fingerprint()  # so clients can suppress by id
        return d

    return json.dumps(
        {"summary": summarize(findings), "findings": [_row(f) for f in findings]},
        indent=2,
    ) + "\n"


def to_sarif(findings: list[Finding]) -> str:
    # One rule descriptor per distinct rule_id.
    rules: dict[str, dict] = {}
    for f in findings:
        if f.rule_id not in rules:
            rules[f.rule_id] = {
                "id": f.rule_id,
                "name": f.title,
                "shortDescription": {"text": f.title},
                "properties": {k: v for k, v in (("cwe", f.cwe), ("owasp", f.owasp)) if v},
            }
    results = []
    for f in findings:
        result = {
            "ruleId": f.rule_id,
            "level": _SARIF_LEVEL.get(f.severity, "warning"),
            "message": {"text": f"{f.title}: {f.rationale}"},
            "partialFingerprints": {"legacylens/v1": f.fingerprint()},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.rel_path},
                        "region": {"startLine": max(f.line, 1)},
                    }
                }
            ],
            "properties": {
                "severity": f.severity,
                "cwe": f.cwe,
                "owasp": f.owasp,
                "confidence": f.confidence,
                "source": f.source,
                "requiresHumanReview": f.requires_human_review,
                "evidence": f.evidence,
                "remediation": f.remediation,
            },
        }
        if f.suppressed:
            # SARIF-standard suppression so consumers (e.g. code scanning) hide it.
            result["suppressions"] = [{"kind": "external"}]
        results.append(result)
    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "legacylens",
                        "version": __version__,
                        "informationUri": "https://github.com/your-org/legacylens",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2) + "\n"


def to_html(findings: list[Finding]) -> str:
    summary = summarize(findings)
    ordered = sorted(findings, key=lambda f: (-SEVERITY_RANK.get(f.severity, 0), f.rel_path, f.line))

    sev_chips = "".join(
        f'<span class="chip" style="background:{_HTML_SEVERITY_COLOR.get(sev, "#577590")}">'
        f"{escape(sev)}: {summary['by_severity'].get(sev, 0)}</span>"
        for sev in ("critical", "high", "medium", "low", "info")
    )

    rows = []
    for f in ordered:
        review = '<span class="review">review</span>' if f.requires_human_review else ""
        supp = '<span class="supp">suppressed</span>' if f.suppressed else ""
        cwe = f'<a href="https://cwe.mitre.org/data/definitions/{escape(f.cwe.split("-")[-1])}.html">{escape(f.cwe)}</a>' if f.cwe else ""
        rows.append(
            f'<tr{" class=off" if f.suppressed else ""}>'
            f'<td><span class="chip" style="background:{_HTML_SEVERITY_COLOR.get(f.severity, "#577590")}">{escape(f.severity)}</span></td>'
            f"<td>{escape(f.rule_id)}</td>"
            f"<td>{cwe}{('<br>' + escape(f.owasp)) if f.owasp else ''}</td>"
            f"<td><code>{escape(f.rel_path)}:{f.line}</code><br><small>id {escape(f.fingerprint())}</small></td>"
            f"<td><strong>{escape(f.title)}</strong> {review}{supp}<br><small>{escape(f.rationale)}</small>"
            f"<br><small><em>Fix:</em> {escape(f.remediation)}</small>"
            f"<br><small><em>Evidence:</em> <code>{escape(f.evidence)}</code></small></td>"
            f"<td>{escape(f.source)}<br><small>conf {f.confidence:.2f}</small></td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>legacylens security report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1d1d1f; }}
  h1 {{ margin-bottom: .25rem; }}
  .meta {{ color: #666; margin-bottom: 1rem; }}
  .chip {{ color: #fff; padding: 2px 8px; border-radius: 10px; font-size: .8rem; white-space: nowrap; }}
  .review {{ background:#444; color:#fff; padding:1px 6px; border-radius:8px; font-size:.7rem; }}
  .supp {{ background:#888; color:#fff; padding:1px 6px; border-radius:8px; font-size:.7rem; }}
  tr.off {{ opacity:.45; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border-bottom: 1px solid #e5e5e5; padding: 8px; text-align: left; vertical-align: top; }}
  th {{ background:#f5f5f7; }}
  code {{ background:#f5f5f7; padding:1px 4px; border-radius:4px; }}
  small {{ color:#555; }}
</style></head>
<body>
  <h1>legacylens security &amp; compliance report</h1>
  <div class="meta">{summary['total']} finding(s) · {summary['requires_human_review']} require human review · generated by legacylens {escape(__version__)}</div>
  <div>{sev_chips}</div>
  <p><small>Findings with the <span class="review">review</span> tag are LLM-advisory and must be confirmed by a human before they are authoritative.</small></p>
  <table>
    <thead><tr><th>Severity</th><th>Rule</th><th>CWE / OWASP</th><th>Location</th><th>Finding</th><th>Source</th></tr></thead>
    <tbody>
      {''.join(rows) if rows else '<tr><td colspan="6">No findings.</td></tr>'}
    </tbody>
  </table>
</body></html>
"""
