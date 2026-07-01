"""Enable `python -m legacylens ...` as a PATH-independent way to run the CLI."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
