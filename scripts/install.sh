#!/usr/bin/env bash
# Install legacylens as a global CLI on Linux/macOS.
#
# Uses pipx, which installs the tool in an isolated environment AND puts it on PATH
# for every shell. Run from the repo root:   bash scripts/install.sh
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
py="$(command -v python3 || command -v python)"

echo "Installing pipx..."
"$py" -m pip install --user --upgrade pipx

echo "Ensuring the CLI directory is on PATH (all shells)..."
"$py" -m pipx ensurepath

echo "Installing legacylens from $repo_root ..."
"$py" -m pipx install --force "$repo_root"

echo
echo "Done. Open a NEW terminal (so PATH refreshes), then run:"
echo "    legacylens --help"
