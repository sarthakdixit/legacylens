"""Append-only audit log.

Every run records a structured, timestamped trail of what it did: which config and
rule-pack versions were used, which provider/model served each task, and which
inputs were analyzed. This is the compliance evidence artifact and is intentionally
separate from console logging.

Records are written as JSON Lines (one JSON object per line) so they are both
human-greppable and machine-parseable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    """A thin append-only JSON Lines writer for run provenance."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **fields: Any) -> None:
        """Append one audit event with a UTC timestamp."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
