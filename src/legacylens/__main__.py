"""Enable `python -m legacylens ...` as a PATH-independent way to run the CLI.

Goes through the bootstrap so the dependency preflight runs here too.
"""

import sys

from .bootstrap import main

if __name__ == "__main__":
    sys.exit(main())
