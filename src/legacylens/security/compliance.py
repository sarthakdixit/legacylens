"""Regulatory compliance frameworks.

A *framework* maps a weakness (by CWE) to one or more control references in a
regulatory standard (PCI DSS, NIST 800-53, ...). Applying frameworks enriches each
finding with the controls it implicates — turning CWE-tagged findings into
audit-ready, control-mapped evidence — without needing new detection rules.

Built-in frameworks are indicative starting points (control mappings are inherently
approximate); clients can ship their own via ``framework_paths`` YAML files:

    name: acme-policy
    title: ACME Secure Coding Policy
    map:
      CWE-798: ["SEC-1.1", "SEC-1.2"]
      CWE-89:  ["SEC-3.4"]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..errors import ConfigError
from .model import Finding


@dataclass
class Framework:
    name: str
    title: str
    mapping: dict[str, list[str]]  # CWE id -> control references


# --- built-in frameworks (indicative CWE -> control mappings) --------------- #
_BUILTIN: dict[str, Framework] = {
    "pci-dss": Framework(
        name="PCI-DSS",
        title="PCI DSS v4.0 (indicative)",
        mapping={
            "CWE-798": ["8.6.2"],   # no hard-coded passwords/keys
            "CWE-259": ["8.6.2"],
            "CWE-89": ["6.2.4"],    # protect against injection
            "CWE-532": ["3.3.1", "10.2.1"],  # mask PAN / audit trail protection
            "CWE-94": ["6.2.4"],
        },
    ),
    "nist-800-53": Framework(
        name="NIST-800-53",
        title="NIST SP 800-53 Rev.5 (indicative)",
        mapping={
            "CWE-798": ["IA-5"],   # authenticator management
            "CWE-259": ["IA-5"],
            "CWE-89": ["SI-10"],   # information input validation
            "CWE-94": ["SI-10"],
            "CWE-532": ["AU-9", "SI-11"],  # protection of audit info / error handling
            "CWE-489": ["SA-15"],  # development process (no debug code)
            "CWE-478": ["SI-10"],
            "CWE-1051": ["CM-6"],  # configuration settings
        },
    ),
}


def load_framework(path: str | Path) -> Framework:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"framework file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or "name" not in data or "map" not in data:
        raise ConfigError(f"invalid framework file (need 'name' and 'map'): {p}")
    return Framework(
        name=str(data["name"]),
        title=str(data.get("title", data["name"])),
        mapping={str(k).upper(): list(v) for k, v in data["map"].items()},
    )


def resolve_frameworks(names: list[str], paths: list[str | Path]) -> list[Framework]:
    """Resolve built-in framework names + custom framework files into Frameworks."""
    frameworks: list[Framework] = []
    for name in names:
        fw = _BUILTIN.get(name.lower())
        if fw is None:
            known = ", ".join(sorted(_BUILTIN))
            raise ConfigError(f"unknown framework '{name}'. Built-in: {known}. Or supply a framework file.")
        frameworks.append(fw)
    for path in paths:
        frameworks.append(load_framework(path))
    return frameworks


def apply_frameworks(findings: list[Finding], frameworks: list[Framework]) -> None:
    """Attach control references to each finding based on its CWE."""
    if not frameworks:
        return
    for f in findings:
        if not f.cwe:
            continue
        controls: list[str] = []
        for fw in frameworks:
            for control in fw.mapping.get(f.cwe.upper(), []):
                controls.append(f"{fw.name}:{control}")
        if controls:
            f.controls = sorted(set(f.controls) | set(controls))
