#!/bin/bash
# CUI // SP-PROPIN
# GovProposal Docker entrypoint — initializes DB and starts dashboard
set -e

echo "=========================================="
echo "  GovProposal Portal"
echo "  Classification: ${GOVPROPOSAL_CUI_BANNER:-CUI // SP-PROPIN}"
echo "=========================================="

# --- Initialize database if it doesn't exist ---
if [ ! -f "${GOVPROPOSAL_DB_PATH:-/app/data/govproposal.db}" ]; then
    echo "[entrypoint] Initializing database..."
    python tools/db/init_db.py --json
    echo "[entrypoint] Database initialized."
else
    echo "[entrypoint] Database already exists at ${GOVPROPOSAL_DB_PATH}"
fi

# --- Start dashboard ---
echo "[entrypoint] Starting GovProposal Dashboard on port ${FLASK_PORT:-5001}..."

exec gunicorn \
    --bind "0.0.0.0:${FLASK_PORT:-5001}" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    "tools.dashboard.app:app"
