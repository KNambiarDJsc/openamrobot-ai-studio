# One-time setup on Windows: Python venv + editable packages, web dependencies.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path .venv)) { py -3 -m venv .venv }
& .\.venv\Scripts\python -m pip install --upgrade pip
& .\.venv\Scripts\python -m pip install -e packages/contracts -e services/agent -e services/api "pytest>=8,<9"
Push-Location apps/web
npm install
Pop-Location
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Setup done. Start with .\scripts\dev.ps1"
