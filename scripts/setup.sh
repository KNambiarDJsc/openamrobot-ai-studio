#!/usr/bin/env bash
# One-time setup on Linux/macOS: Python venv + editable packages, web dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e packages/contracts -e services/agent -e services/api "pytest>=8,<9"
(cd apps/web && npm install)
[ -f .env ] || cp .env.example .env
echo "Setup done. Start with ./scripts/dev.sh"
