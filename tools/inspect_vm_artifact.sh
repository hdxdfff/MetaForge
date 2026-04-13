#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
./.venv/bin/python - <<'PY'
from pathlib import Path
import json
from tools.artifact_audit import evaluate_artifact

print(json.dumps(evaluate_artifact(Path("/srv/generated/toy-os-demo")), ensure_ascii=False, indent=2))
PY
