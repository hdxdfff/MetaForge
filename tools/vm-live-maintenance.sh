#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp

PYTHON="/srv/orchestrator-mvp/.venv/bin/python"

echo "[vm-live-maintenance] daemon-status"
"$PYTHON" tools/codex_control.py daemon-status

echo "[vm-live-maintenance] active-tasks"
"$PYTHON" tools/codex_control.py tasks --active-only

echo "[vm-live-maintenance] runtime-maintenance"
"$PYTHON" tools/codex_control.py runtime-maintenance

echo "[vm-live-maintenance] active-tasks-after"
"$PYTHON" tools/codex_control.py tasks --active-only
