"""Source file discovery.

Walks the project root and yields candidate files, skipping anything matched by the
configured exclude globs plus a small set of always-ignored directories (VCS,
virtualenvs, the tool's own output). Symlinks are not followed, to avoid escaping
the project root or cycling.

Exclude globs use gitignore-style ``**`` semantics (``**/`` matches zero or more
leading directories), which the stdlib ``fnmatch`` does not provide, so patterns are
compiled to regexes here.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

_ALWAYS_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", ".legacylens"}


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob (with ``**`` support) to an anchored regex.

    * ``**/`` → zero or more leading path segments
    * ``**``  → anything, including ``/``
    * ``*``   → anything except ``/``
    * ``?``   → a single non-``/`` char
    """
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        if pattern[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


class _Excluder:
    def __init__(self, patterns: list[str]):
        self._patterns = patterns
        self._regexes = [_glob_to_regex(p) for p in patterns]

    def matches_path(self, rel_path: str) -> bool:
        name = rel_path.rsplit("/", 1)[-1]
        return any(rx.match(rel_path) or rx.match(name) for rx in self._regexes)

    def prunes_dir(self, rel_dir: str) -> bool:
        # Descend-avoidance: skip a directory if it (or its tree) is excluded.
        for pat, rx in zip(self._patterns, self._regexes):
            if rx.match(rel_dir):
                return True
            if pat.endswith("/**") and _glob_to_regex(pat[:-3]).match(rel_dir):
                return True
        return False


def discover(root: str | Path, exclude: list[str] | None = None) -> Iterator[Path]:
    """Yield files under ``root`` that are not excluded.

    Paths are yielded as absolute :class:`~pathlib.Path` objects; exclusion globs are
    evaluated against the path relative to ``root`` (POSIX separators).
    """
    root = Path(root).resolve()
    excluder = _Excluder(exclude or [])
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        kept = []
        for d in dirnames:
            if d in _ALWAYS_SKIP_DIRS:
                continue
            rel_dir = Path(dirpath, d).resolve().relative_to(root).as_posix()
            if excluder.prunes_dir(rel_dir):
                continue
            kept.append(d)
        dirnames[:] = kept

        for filename in filenames:
            abs_path = Path(dirpath, filename)
            rel = abs_path.resolve().relative_to(root).as_posix()
            if excluder.matches_path(rel):
                continue
            yield abs_path
