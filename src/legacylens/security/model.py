"""Finding model shared by rules, the analyzer, and emitters."""

from __future__ import annotations

import enum
import hashlib
from dataclasses import asdict, dataclass


class Severity(str, enum.Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# Ordering for sorting/summaries (higher = more severe).
SEVERITY_RANK: dict[str, int] = {
    Severity.info.value: 0,
    Severity.low.value: 1,
    Severity.medium.value: 2,
    Severity.high.value: 3,
    Severity.critical.value: 4,
}


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: str
    rel_path: str
    line: int
    evidence: str
    rationale: str
    remediation: str
    confidence: float
    source: str  # "rule" | "llm"
    requires_human_review: bool
    cwe: str | None = None
    owasp: str | None = None
    # Set True when a matching suppression exists (false positive / accepted).
    suppressed: bool = False
    # Regulatory control references (e.g. "PCI-DSS:8.6.2"), from active frameworks.
    controls: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.controls is None:
            self.controls = []

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(**data)

    @property
    def rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 0)

    def fingerprint(self) -> str:
        """Stable identity across runs — deliberately excludes the line number so a
        finding survives edits above it. Keyed on rule, file, CWE, title, evidence."""
        blob = "|".join(
            [self.rule_id, self.rel_path, self.cwe or "", self.title, self.evidence]
        )
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
