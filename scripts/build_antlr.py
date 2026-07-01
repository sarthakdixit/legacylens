#!/usr/bin/env python3
"""Generate the ANTLR COBOL parser for legacylens.

This is a one-time build step for clients who opt into the ANTLR parser backend
(`parser.backend: antlr`). It runs the ANTLR tool over
`src/legacylens/parsing/antlr/Cobol.g4` and writes the generated Python parser into
`src/legacylens/parsing/antlr/_generated/`.

Requirements (build-time only — NOT needed at runtime):
  * Java (JRE 11+) on PATH, OR `pip install antlr4-tools` (which fetches a JRE)
  * The ANTLR tool. Easiest: `pip install antlr4-tools` then this script uses the
    `antlr4` command it installs.

At runtime only `antlr4-python3-runtime` is required:  pip install 'legacylens[antlr]'

Usage:
    python scripts/build_antlr.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAMMAR = HERE.parent / "src" / "legacylens" / "parsing" / "antlr" / "Cobol.g4"
OUT_DIR = GRAMMAR.parent / "_generated"


def _find_antlr_cmd() -> list[str] | None:
    # Prefer the `antlr4` launcher from the pip `antlr4-tools` package.
    if shutil.which("antlr4"):
        return ["antlr4"]
    # Fall back to a local ANTLR jar via java, if provided.
    if shutil.which("java"):
        jar = HERE / "antlr-4.13.2-complete.jar"
        if jar.exists():
            return ["java", "-jar", str(jar), "org.antlr.v4.Tool"]
    return None


def main() -> int:
    if not GRAMMAR.exists():
        print(f"grammar not found: {GRAMMAR}", file=sys.stderr)
        return 1

    cmd = _find_antlr_cmd()
    if cmd is None:
        print(
            "ANTLR tool not found.\n"
            "  Install it with:  pip install antlr4-tools\n"
            "  (it downloads a JRE on first run), then re-run this script.\n"
            "  Or place antlr-4.13.2-complete.jar in scripts/ with Java on PATH.",
            file=sys.stderr,
        )
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "__init__.py").write_text("", encoding="utf-8")

    full = cmd + [
        "-Dlanguage=Python3",
        "-visitor",
        "-listener",
        "-o",
        str(OUT_DIR),
        str(GRAMMAR),
    ]
    print("running:", " ".join(full))
    result = subprocess.run(full)
    if result.returncode != 0:
        print("ANTLR generation failed.", file=sys.stderr)
        return result.returncode

    print(f"Generated ANTLR COBOL parser into {OUT_DIR}")
    print("Set `parser.backend: antlr` in your audit.yaml to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
