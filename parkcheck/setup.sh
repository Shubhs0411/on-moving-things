#!/usr/bin/env bash
# Can I Park Here? — one-command local setup
# Usage: bash setup.sh

set -e

GREEN='\033[0;32m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}🅿  Can I Park Here? — setup${RESET}"
echo "────────────────────────────────────"

# Python version check
PY=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PY" | cut -d. -f1)
MINOR=$(echo "$PY" | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
  echo "❌  Python 3.11+ is required (you have $PY)"
  echo "    Download it at: https://www.python.org/downloads/"
  exit 1
fi
echo -e "✓  Python $PY"

# Virtual environment
if [ ! -d ".venv" ]; then
  echo "→  Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo -e "✓  Virtual environment active"

# Dependencies
echo "→  Installing dependencies (this takes ~30 seconds the first time)..."
pip install -q -r requirements.txt
echo -e "✓  Dependencies installed"

# Done
echo ""
echo -e "${GREEN}${BOLD}All set! Starting the app…${RESET}"
echo ""
echo "    Open http://localhost:8000 in your browser"
echo "    Press Ctrl+C to stop"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
