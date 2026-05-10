#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <query>" >&2
  exit 2
fi

cd /mnt/d/codex/local-mind
. .venv/bin/activate
python memory_store.py --search "$*" --vector
