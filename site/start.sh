#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  Nyx Ichos"
echo "  Local-first AI agent — created by Shagnik"
echo "  ---------------------------------------------------"
echo

fail() {
    echo
    echo "  PROBLEM: $1"
    echo
    exit 1
}

# --- 1. Python -------------------------------------------------------------
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
    echo "  [1/4] Using the existing environment."
else
    echo "  [1/4] First run — creating the Python environment..."
    if command -v python3 >/dev/null 2>&1; then
        BOOTSTRAP=python3
    elif command -v python >/dev/null 2>&1; then
        BOOTSTRAP=python
    else
        fail "Python is not installed. Get it from https://www.python.org/downloads/"
    fi
    "$BOOTSTRAP" -m venv .venv || fail "could not create the environment."
    PY=".venv/bin/python"
fi

# --- 2. Dependencies -------------------------------------------------------
if "$PY" -c "import fastapi" >/dev/null 2>&1; then
    echo "  [2/4] Dependencies are already installed."
else
    echo "  [2/4] Installing dependencies — this takes a minute, once..."
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r requirements.txt \
        || fail "dependencies failed to install. Check your connection and retry."
fi

# --- 3. The workspace UI ---------------------------------------------------
if [ -f "frontend/nyx-pulse/dist/app/index.html" ]; then
    echo "  [3/4] Workspace is already built."
elif command -v npm >/dev/null 2>&1; then
    echo "  [3/4] Building the workspace — this takes a minute, once..."
    (cd frontend/nyx-pulse && npm install --silent && npm run build --silent)
else
    echo "  [3/4] Node.js not found — skipping the browser workspace."
    echo "        The API and the terminal app (python cli.py) still work."
fi

# --- 4. Launch -------------------------------------------------------------
echo "  [4/4] Starting the engine..."
echo
echo "  ---------------------------------------------------"
echo "  Opening http://localhost:8000 in your browser."
echo
echo "  Leave this terminal open while you use Nyx."
echo "  Press Ctrl+C to stop."
echo "  ---------------------------------------------------"
echo

(
    sleep 3
    if command -v open >/dev/null 2>&1; then open http://localhost:8000
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:8000
    fi
) >/dev/null 2>&1 &

exec "$PY" -m uvicorn server:app --host 127.0.0.1 --port 8000
