#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python tools/codex_control.py --session-token e6c0bcc374a0dbd2b3f14ee149c5dbc0 brain-loop
