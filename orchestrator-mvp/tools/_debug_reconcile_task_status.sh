#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python tools/reconcile_task_status_from_context.py
