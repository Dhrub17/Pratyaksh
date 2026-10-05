#!/usr/bin/env bash
# One-command local demo (macOS / Linux). Windows: see run_demo.ps1
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
python scripts/simulate_fleet.py --direct --reset --days 14
uvicorn app.main:app --port 8000 &
API_PID=$!
trap "kill $API_PID" EXIT
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
echo "Dashboard: http://localhost:5173   API docs: http://localhost:8000/docs"
npm run dev
