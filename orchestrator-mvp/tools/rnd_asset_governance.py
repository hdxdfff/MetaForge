from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.artifact_audit import audit_artifacts, build_reality_dashboard
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
FACTORY = ROOT / "factory"
OUT = DATA / "rnd_asset_governance_status.json"
KNOWLEDGE = DATA / "knowledge_base.json"
CAPABILITIES = FACTORY / "capability_registry.json"
PLATFORMS = FACTORY / "platform_registry.json"
VERIFICATION = DATA / "verification_status.json"
RELEASE_OPS = DATA / "release_operations_status.json"
ORG = DATA / "organization_model.json"
PROJECT_GRAPH = DATA / "project_graph.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def build_rnd_asset_governance_status() -> dict[str, Any]:
    knowledge = _load_json(KNOWLEDGE, {})
    capability_registry = _load_json(CAPABILITIES, {})
    platform_registry = _load_json(PLATFORMS, {})
    verification = _load_json(VERIFICATION, {})
    release_ops = _load_json(RELEASE_OPS, {})
    organization = _load_json(ORG, {})
    project_graph = _load_json(PROJECT_GRAPH, {})
    artifact_registry = audit_artifacts(write_outputs=True)
    reality_dashboard = build_reality_dashboard(write_outputs=True)

    capabilities = capability_registry.get("capabilities", [])
    platforms = platform_registry.get("platforms", [])
    repo_learning = knowledge.get("repo_learning") or {}
    github_learning = knowledge.get("github_learning") or {}

    product_projects = [
        item
        for item in (organization.get("project_allocations") or [])
        if "frontend" in (item.get("domains") or []) or "service" in (item.get("domains") or [])
    ]

    assets = {
        "code_assets": {
            "status": "ready" if len(capabilities) >= 10 else "building",
            "capability_count": len(capabilities),
            "platform_count": len(platforms),
        },
        "knowledge_assets": {
            "status": "ready" if repo_learning.get("chunk_count", 0) >= 100 else "building",
            "experiment_pattern_count": len(knowledge.get("experiment_patterns", [])),
            "decision_pattern_count": len(knowledge.get("decision_patterns", [])),
            "repo_learning_chunks": repo_learning.get("chunk_count", 0),
        },
        "data_assets": {
            "status": "building",
            "benchmark_count": len(project_graph.get("edges", [])),
            "learned_repository_count": repo_learning.get("learned_repository_count", 0),
            "github_ready_repo_count": github_learning.get("ready_repo_count", 0),
        },
        "automation_assets": {
            "status": "ready" if (verification.get("patch_gate") or {}).get("status") == "pass" else "attention",
            "verification_status": verification.get("status"),
            "patch_gate_status": (verification.get("patch_gate") or {}).get("status"),
            "runtime_health_status": (verification.get("runtime_health") or {}).get("status"),
        },
        "platform_assets": {
            "status": "ready" if len(platforms) >= 8 else "building",
            "platform_count": len(platforms),
            "real_artifact_count": artifact_registry.get("real_artifact_count", 0),
            "project_count": project_graph.get("project_count", 0),
        },
        "product_assets": {
            "status": "ready" if reality_dashboard.get("products_real", 0) > 0 else "building",
            "product_project_count": len(product_projects),
            "real_product_count": reality_dashboard.get("products_real", 0),
            "release_train_status": (release_ops.get("release_train") or {}).get("status"),
        },
    }

    automation_ratio = round(
        ((1.0 if assets["automation_assets"]["status"] == "ready" else 0.4) + min(1.0, len(platforms) / 10.0) + min(1.0, repo_learning.get("chunk_count", 0) / 150.0)) / 3.0,
        4,
    )

    payload = {
        "updated_at": _utc(),
        "status": "managed" if automation_ratio >= 0.7 else "building",
        "asset_domains": assets,
        "kpi": {
            "technology_asset_growth": round(len(capabilities) + len(platforms) + len(knowledge.get("experiment_patterns", [])), 4),
            "release_readiness": 1.0 if (release_ops.get("release_train") or {}).get("status") == "ready" else 0.5,
            "automation_ratio": automation_ratio,
            "system_stability": 1.0 if (verification.get("patch_gate") or {}).get("status") == "pass" else 0.5,
            "platform_output": len(platforms),
            "product_output": len(product_projects),
            "real_artifact_output": artifact_registry.get("real_artifact_count", 0),
            "prototype_artifact_output": artifact_registry.get("prototype_artifact_count", 0),
            "real_product_output": reality_dashboard.get("products_real", 0),
            "task_to_artifact_conversion_rate": reality_dashboard.get("conversion_rate", 0.0),
        },
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_rnd_asset_governance_status(), ensure_ascii=False, indent=2))
