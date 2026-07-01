"""Dependency preflight — stdlib only.

Runs before the rest of the package is imported (the CLI is built on these libs, so
they must be verified first). If any required package is missing, the client is asked
for permission to install it with pip; nothing is installed without consent.

Set ``LEGACYLENS_AUTO_INSTALL=1`` to consent non-interactively (e.g. in CI/scripts).
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

# import-name -> pip requirement
REQUIRED: list[tuple[str, str]] = [
    ("click", "click>=8.1"),
    ("yaml", "pyyaml>=6.0"),
    ("pydantic", "pydantic>=2.5"),
    ("rich", "rich>=13.0"),
]


def _missing() -> list[tuple[str, str]]:
    return [(imp, spec) for imp, spec in REQUIRED if importlib.util.find_spec(imp) is None]


def _consented(specs: list[str]) -> bool:
    if os.environ.get("LEGACYLENS_AUTO_INSTALL") == "1":
        return True
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            answer = input(f"Install now with pip ({' '.join(specs)})? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in ("y", "yes")
    return False


def ensure_dependencies() -> None:
    """Verify required packages; offer to pip-install missing ones (with consent)."""
    missing = _missing()
    if not missing:
        return

    names = ", ".join(imp for imp, _ in missing)
    specs = [spec for _, spec in missing]
    manual = f"  {sys.executable} -m pip install {' '.join(specs)}"
    sys.stderr.write(f"legacylens: required package(s) not installed: {names}\n")

    if not _consented(specs):
        sys.stderr.write("Cannot continue without them. Install with:\n" + manual + "\n")
        raise SystemExit(1)

    sys.stderr.write("Installing missing package(s)...\n")
    import subprocess  # local import keeps module import light

    rc = subprocess.call([sys.executable, "-m", "pip", "install", *specs])
    importlib.invalidate_caches()
    if rc != 0 or _missing():
        sys.stderr.write("Install failed. Please install manually:\n" + manual + "\n")
        raise SystemExit(1)
    sys.stderr.write("Dependencies installed.\n")
