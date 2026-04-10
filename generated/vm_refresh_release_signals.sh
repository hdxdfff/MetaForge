#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools.verification_engine import run_verification
from tools.autonomy_score import run_autonomy_score
from tools.meta_factory_control import run_control_layer
import json

verification = run_verification()
autonomy = run_autonomy_score()
control = run_control_layer(verification_snapshot=verification)

print(json.dumps({
    "verification_status": verification.get("status"),
    "verification_release_gate": verification.get("release_gate"),
    "artifact_audit": (verification.get("checks") or {}).get("artifact_audit"),
    "reality_dashboard": (verification.get("checks") or {}).get("reality_dashboard"),
    "autonomy_score": {
        "score": autonomy.get("score"),
        "stage": autonomy.get("stage"),
        "quality_score": autonomy.get("quality_score"),
        "quality_status": autonomy.get("quality_status"),
        "production": (autonomy.get("metrics") or {}).get("production"),
    },
    "control_layer": {
        "status": control.get("status"),
        "decision_engine": control.get("decision_engine"),
        "quality_system": control.get("quality_system"),
        "release_operations": control.get("release_operations"),
    },
}, ensure_ascii=False, indent=2))
PY'
