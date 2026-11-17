#!/usr/bin/env bash
# Start the API (port 8000) and the web app (port 3000). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
.venv/bin/python -m uvicorn studio_api.app:create_app --factory --host 127.0.0.1 --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
(cd apps/web && npx next dev -H 127.0.0.1 -p 3000)
