#!/usr/bin/env bash
# Build an offline install bundle for air-gapped environments.
#
# Produces dist/wheelhouse/ containing the legacylens wheel plus every dependency
# wheel. Copy that folder to the air-gapped host and install with NO network:
#
#   pip install --no-index --find-links wheelhouse legacylens
#   # with the ANTLR runtime extra:
#   pip install --no-index --find-links wheelhouse "legacylens[antlr]"
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
py="$(command -v python3 || command -v python)"
out="$repo_root/dist/wheelhouse"

rm -rf "$out"
mkdir -p "$out"

echo "Building legacylens + dependency wheels into $out ..."
# `pip wheel .` builds the project wheel AND resolves+builds all dependency wheels.
"$py" -m pip wheel "$repo_root" -w "$out"
# Include the optional ANTLR runtime so [antlr] installs offline too.
"$py" -m pip wheel "antlr4-python3-runtime>=4.13" -w "$out"

echo
echo "Offline bundle ready: $out ($(ls "$out" | wc -l) wheels)"
echo "On the air-gapped host:"
echo "  pip install --no-index --find-links wheelhouse legacylens"
