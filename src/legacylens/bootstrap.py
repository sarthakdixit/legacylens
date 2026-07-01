"""CLI entry point wrapper.

Verifies third-party dependencies are present (installing them with the client's
permission if not) *before* importing the CLI, which depends on them. This is the
target of the ``legacylens`` console script.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    from ._preflight import ensure_dependencies

    ensure_dependencies()

    from .cli import main as cli_main  # imported only after deps are verified

    return cli_main(argv)
