# Build an offline install bundle for air-gapped environments (Windows).
#
# Produces dist\wheelhouse\ with the legacylens wheel plus every dependency wheel.
# Copy that folder to the air-gapped host and install with NO network:
#
#   pip install --no-index --find-links wheelhouse legacylens
#   pip install --no-index --find-links wheelhouse "legacylens[antlr]"
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$out = Join-Path $repoRoot "dist\wheelhouse"

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host "Building legacylens + dependency wheels into $out ..."
python -m pip wheel "$repoRoot" -w "$out"
python -m pip wheel "antlr4-python3-runtime>=4.13" -w "$out"

Write-Host ""
Write-Host "Offline bundle ready: $out"
Write-Host "On the air-gapped host:"
Write-Host "  pip install --no-index --find-links wheelhouse legacylens"
