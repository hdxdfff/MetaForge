#!/usr/bin/env bash
set -euo pipefail

: "${CODEX_VM_PASSWORD:=CodexVm2026}"

printf '%s\n' "$CODEX_VM_PASSWORD" | sudo -S -p '' bash -lc '
set -euo pipefail
find /srv/orchestrator-mvp -type d -name __pycache__ -print0 | xargs -0 -r chown -R codex:codex
find /srv/orchestrator-mvp -type d -name __pycache__ -print0 | xargs -0 -r chmod -R u+rwX,go+rX
'

find /srv/orchestrator-mvp -type d -name __pycache__ -printf "%u:%g:%m %p\n" | sort | head -n 20
