"""Finding model shared by rules, the analyzer, and emitters."""

from __future__ import annotations

import enum
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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(**data)

    @property
    def rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 0)
