# Install legacylens as a global CLI on Windows (works in cmd and PowerShell).
#
# Uses pipx, which installs the tool in an isolated environment AND puts it on PATH
# for every shell. Run from the repo root:   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Installing pipx..."
python -m pip install --user --upgrade pipx

Write-Host "Ensuring the CLI directory is on PATH (all shells)..."
python -m pipx ensurepath

Write-Host "Installing legacylens from $repoRoot ..."
python -m pipx install --force "$repoRoot"

Write-Host ""
Write-Host "Done. Open a NEW terminal (so PATH refreshes), then run:"
Write-Host "    legacylens --help"
