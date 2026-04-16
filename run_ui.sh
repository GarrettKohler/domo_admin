#!/usr/bin/env bash
# Launch the GSTV Domo Governance UI.
# Usage: ./run_ui.sh [--port 8501]
#
# Installs streamlit/pandas if they're missing, then starts the app from the
# project root so relative paths (./.cache, ./output, ./column_definitions.csv)
# all resolve correctly.
set -euo pipefail

cd "$(dirname "$0")"

# Make sure the UI deps exist — fall back to a graceful message if pip fails.
if ! python3 -c "import streamlit, pandas" 2>/dev/null; then
  echo "Installing UI dependencies (streamlit, pandas)…"
  python3 -m pip install -r requirements.txt
fi

exec python3 -m streamlit run ui/app.py "$@"
