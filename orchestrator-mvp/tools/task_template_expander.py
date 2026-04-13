from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

TEMPLATES_PATH = DATA / "task_templates.json"
OUTPUT_PATH = DATA / "task_template_expansion_report.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


NEW_TEMPLATES = [
    {
        "id": "self-repair-technical",
        "name": "Self Repair Technical Task",
        "category": "repair",
        "prompt": "Detect a bounded system issue, emit a self_repair task with a clear trigger, target component, verification plan, and expected fix signal.",
        "goal": "Turn runtime problems into repairable tasks.",
        "recommended_context_mode": "lean",
        "default_allow_resource_scan": True,
        "default_allow_repo_status": True,
        "task_type": "self_repair",
        "queue_name": "self_improvement",
        "verification_level": "L1",
        "max_runtime_seconds": 1800,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
    },
    {
        "id": "capability-expansion-technical",
        "name": "Capability Expansion Technical Task",
        "category": "expansion",
        "prompt": "Identify a missing reusable capability, emit a capability_expansion task, and specify the future tasks it will unblock.",
        "goal": "Expand the system with small reusable capabilities.",
        "recommended_context_mode": "lean",
        "default_allow_resource_scan": True,
        "default_allow_repo_status": True,
        "task_type": "capability_expansion",
        "queue_name": "fastlane",
        "verification_level": "L2",
        "max_runtime_seconds": 2400,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
    },
    {
        "id": "technical-artifact-growth",
        "name": "Technical Artifact Growth Task",
        "category": "artifact",
        "prompt": "Generate a minimal real technical artifact bundle with manifest, evidence, self-test, and execution proof.",
        "goal": "Keep real artifact production continuous.",
        "recommended_context_mode": "lean",
        "default_allow_resource_scan": True,
        "default_allow_repo_status": True,
        "task_type": "technical_artifact",
        "queue_name": "artifact_growth",
        "verification_level": "L1",
        "max_runtime_seconds": 1800,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
    },
]


def run_task_template_expander() -> dict[str, Any]:
    templates = _load_json(TEMPLATES_PATH, [])
    if not isinstance(templates, list):
        templates = []
    existing_ids = {str(item.get("id") or "") for item in templates if isinstance(item, dict)}
    added = 0
    for item in NEW_TEMPLATES:
        if item["id"] in existing_ids:
            continue
        templates.append(item)
        existing_ids.add(item["id"])
        added += 1
    atomic_write_json(TEMPLATES_PATH, templates)
    report = {
        "updated_at": _utc(),
        "status": "pass",
        "added_templates": added,
        "template_count": len(templates),
        "templates_path": str(TEMPLATES_PATH),
    }
    atomic_write_json(OUTPUT_PATH, report)
    return report


def main() -> int:
    _ = argparse.ArgumentParser(description="Expand reusable task templates for Stage 5 success amplifiers.").parse_args()
    print(json.dumps(run_task_template_expander(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
