#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
import json
import pathlib

for path in ["data/reality_dashboard.json", "data/artifact_registry.json", "data/verification_status.json"]:
    p = pathlib.Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    print(f"== {path} ==")
    if path.endswith("reality_dashboard.json"):
        print(json.dumps({
            k: data.get(k)
            for k in [
                "updated_at",
                "status",
                "products_real",
                "technical_real_artifacts",
                "artifacts_total",
                "artifacts_produced_last_24h",
                "technical_conversion_rate",
                "value_conversion_rate",
                "focus_artifact_id",
                "focus_artifact_real",
                "focus_artifact_valuable",
                "recent_real_artifact_ids",
                "recent_technical_real_artifact_ids",
            ]
        }, ensure_ascii=False, indent=2))
    elif path.endswith("artifact_registry.json"):
        artifacts = data.get("artifacts") or []
        print(json.dumps({
            "updated_at": data.get("updated_at"),
            "status": data.get("status"),
            "artifact_count": data.get("artifact_count"),
            "real_artifact_count": data.get("real_artifact_count"),
            "valuable_artifact_count": data.get("valuable_artifact_count"),
            "prototype_artifact_count": data.get("prototype_artifact_count"),
            "top_artifacts": [
                {
                    "artifact_id": item.get("artifact_id"),
                    "kind": item.get("kind"),
                    "real": item.get("real"),
                    "valuable": (item.get("value") or {}).get("valuable"),
                    "status": item.get("status"),
                    "path": item.get("path"),
                }
                for item in artifacts[:10]
            ],
        }, ensure_ascii=False, indent=2))
    else:
        checks = data.get("checks") or {}
        print(json.dumps({
            "updated_at": data.get("updated_at"),
            "status": data.get("status"),
            "artifact_audit": checks.get("artifact_audit"),
            "reality_dashboard": checks.get("reality_dashboard"),
            "release_gate": data.get("release_gate"),
        }, ensure_ascii=False, indent=2))
PY'
