#!/usr/bin/env bash
set -euo pipefail

cd /mnt/d/codex/local-mind

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install -q -r requirements.txt
python procedural_manager.py "$@"
