#!/usr/bin/env bash
set -euo pipefail

exec /srv/orchestrator-mvp/.venv/bin/python /srv/orchestrator-mvp/tools/goose_vm.py "$@"
