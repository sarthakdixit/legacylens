"""Findings lifecycle: suppressions, baseline, and diff.

* **Suppressions** — fingerprints the client has marked as false positives or
  accepted (e.g. confirmed LLM-advisory findings). Suppressed findings are excluded
  from CI gating and from "new" counts.
* **Baseline** — a snapshot of finding fingerprints from a prior run. Used to report
  what is *new* vs *resolved* and to gate only on newly-introduced findings.

All identity is by :meth:`Finding.fingerprint`, which is line-independent so findings
survive edits elsewhere in a file.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Finding


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def write_baseline(path: str | Path, findings: list[Finding]) -> int:
    fingerprints = sorted({f.fingerprint() for f in findings})
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"fingerprints": fingerprints}, indent=2), encoding="utf-8")
    return len(fingerprints)


def load_baseline(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).get("fingerprints", []))


def diff(findings: list[Finding], baseline: set[str]) -> tuple[list[Finding], list[str]]:
    """Return (new findings not in baseline, resolved fingerprints no longer present)."""
    current = {f.fingerprint(): f for f in findings}
    new = [f for fp, f in current.items() if fp not in baseline]
    resolved = sorted(fp for fp in baseline if fp not in current)
    return new, resolved


# --------------------------------------------------------------------------- #
# Suppressions
# --------------------------------------------------------------------------- #
def load_suppressions(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["fingerprint"]: e.get("reason", "") for e in data.get("suppressions", [])}


def add_suppression(path: str | Path, fingerprint: str, reason: str = "") -> bool:
    """Add a suppression; return True if newly added, False if already present."""
    p = Path(path)
    data = (
        json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"suppressions": []}
    )
    existing = {e["fingerprint"] for e in data["suppressions"]}
    if fingerprint in existing:
        return False
    data["suppressions"].append({"fingerprint": fingerprint, "reason": reason})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def apply_suppressions(findings: list[Finding], suppressions: dict[str, str]) -> int:
    """Mark findings whose fingerprint is suppressed. Returns the count suppressed."""
    count = 0
    for f in findings:
        if f.fingerprint() in suppressions:
            f.suppressed = True
            count += 1
    return count
