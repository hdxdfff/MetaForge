from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
STATUS = DATA / "production_focus_status.json"
ARTIFACT_REGISTRY = DATA / "artifact_registry.json"
REALITY = DATA / "reality_dashboard.json"
PRIORITY_DIRECTIVES = DATA / "priority_directives.json"

PRIMARY_ARTIFACT_ID = "toy-os-demo"
PRIMARY_TARGET = "Restore ToyOS real artifact delivery"
PRIMARY_ARTIFACT_PATH = "generated/toy-os-demo"
PRIMARY_REQUIRED_ARTIFACTS = [
    "generated/toy-os-demo/build-report.json",
    "generated/toy-os-demo/build/build.log",
    "generated/toy-os-demo/build/kernel.bin",
    "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
    "generated/toy-os-demo/build/artifact.sha256",
    "generated/toy-os-demo/artifact_manifest.json",
]
FOCUS_KEYWORDS = ("toyos", "toy-os", "toy os", "kernel.bin", "qemu")


def _authoritative_production_repo_path() -> str:
    if os.name != "nt":
        if Path("/workspace").exists():
            return "/workspace"
        if ROOT.exists():
            return str(ROOT)
    return str(ROOT.parent)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    for delay in (0.0, 0.01, 0.02):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            if delay:
                time.sleep(delay)
        except Exception:
            return default
    return default


def _primary_artifact_record() -> dict[str, Any]:
    registry = _load_json(ARTIFACT_REGISTRY, {}) or {}
    for item in registry.get("artifacts", []) or []:
        if str(item.get("artifact_id") or "").strip().lower() == PRIMARY_ARTIFACT_ID:
            return item
    return {}


def _priority_directive() -> dict[str, Any]:
    return _load_json(PRIORITY_DIRECTIVES, {}) or {}


def _single_product_enabled(schedule: dict[str, Any] | None, artifact: dict[str, Any], reality: dict[str, Any]) -> tuple[bool, str]:
    schedule = schedule or {}
    directive = _priority_directive()
    if str(directive.get("highest_priority_project") or "").strip().lower() == PRIMARY_ARTIFACT_ID:
        return True, "priority-directive-toyos"
    if bool(directive.get("force_single_product_mode")):
        return True, "priority-directive-single-product"
    if bool(schedule.get("single_product_mode")):
        return True, "policy-single-product-mode"
    if bool(schedule.get("production_focus_only")):
        return True, "policy-production-focus-only"
    if int(reality.get("products_real") or 0) <= 0:
        return True, "no-real-artifacts"
    if artifact and not bool(artifact.get("real")):
        return True, "primary-artifact-not-real"
    return False, "sufficient-real-artifacts"


def build_production_focus(schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    artifact = _primary_artifact_record()
    reality = _load_json(REALITY, {}) or {}
    directive = _priority_directive()
    enabled, reason = _single_product_enabled(schedule, artifact, reality)
    return {
        "updated_at": _utc(),
        "enabled": enabled,
        "single_product_mode": enabled,
        "reason": reason,
        "primary_artifact_id": PRIMARY_ARTIFACT_ID,
        "primary_artifact_path": PRIMARY_ARTIFACT_PATH,
        "primary_target": PRIMARY_TARGET,
        "primary_required_artifacts": list(PRIMARY_REQUIRED_ARTIFACTS),
        "target_keywords": list(FOCUS_KEYWORDS),
        "artifact": {
            "artifact_id": artifact.get("artifact_id") or PRIMARY_ARTIFACT_ID,
            "status": artifact.get("status") or "missing",
            "real": bool(artifact.get("real")),
            "issues": list(artifact.get("issues") or []),
            "verified": artifact.get("verified") or {},
        },
        "reality": {
            "products_real": int(reality.get("products_real") or 0),
            "conversion_rate": float(reality.get("conversion_rate") or 0.0),
        },
        "priority_directive": {
            "highest_priority_project": directive.get("highest_priority_project"),
            "force_single_product_mode": bool(directive.get("force_single_product_mode")),
            "soak_focus_artifact_id": ((directive.get("soak_focus") or {}).get("artifact_id")),
            "soak_required_hours": ((directive.get("soak_focus") or {}).get("required_hours")),
        },
        "goal_template": {
            "target": PRIMARY_TARGET,
            "goal_type": "build_product",
            "pool": "production",
            "priority": "P0",
            "release_tier": "mainline",
            "assigned_department": "engineering_department",
            "priority_class": "runtime",
            "goal_class": "artifact-delivery",
            "primary_artifact_id": PRIMARY_ARTIFACT_ID,
            "repo_path": _authoritative_production_repo_path(),
            "notes": "Single-product production mode. Convert generated/toy-os-demo from prototype to real artifact by refreshing build, test, and evidence outputs.",
        },
    }


def write_production_focus_status(schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = build_production_focus(schedule)
    atomic_write_json(STATUS, payload)
    return payload


def goal_matches_focus(goal: dict[str, Any] | None, focus: dict[str, Any] | None = None) -> bool:
    goal = goal or {}
    focus = focus or build_production_focus()
    artifact_id = str(goal.get("primary_artifact_id") or "").strip().lower()
    if artifact_id and artifact_id == str(focus.get("primary_artifact_id") or "").strip().lower():
        return True
    corpus = " ".join(
        [
            str(goal.get("target") or ""),
            str(goal.get("notes") or ""),
            str(goal.get("goal_class") or ""),
        ]
    ).lower()
    return any(token in corpus for token in (focus.get("target_keywords") or []))


if __name__ == "__main__":
    print(json.dumps(write_production_focus_status(), ensure_ascii=False, indent=2))
