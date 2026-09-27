#!/usr/bin/env bash
# J.A.R.V.I.S. launcher (macOS/Linux)
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
    echo "[JARVIS] Creating virtual environment..."
    python3 -m venv .venv
fi

echo "[JARVIS] Installing/refreshing dependencies..."
".venv/bin/python" -m pip install -r requirements.txt

echo "[JARVIS] Starting interface..."
# This is the user's own machine, so PC-control tools may be armed.
JARVIS_SYSTEM_CONTROL=1 ".venv/bin/python" -m streamlit run app.py
