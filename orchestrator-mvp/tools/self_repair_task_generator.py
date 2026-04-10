from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.amplifier_observability import record_run
from tools.execution_trace import append_trace

QUEUE_PATH = DATA / "self_improvement_queue.json"
DAEMON_PATH = DATA / "factory_daemon_state.json"
RELEASE_OPS_PATH = DATA / "release_operations_status.json"
CONTROL_LAYER_PATH = DATA / "control_layer_status.json"
AUTONOMY_PATH = DATA / "autonomy_score.json"
GOAL_BACKLOG_PATH = DATA / "goal_backlog_status.json"
PROVIDER_GATEWAY_PATH = DATA / "provider_gateway_state.json"
NETWORK_STATE_PATH = DATA / "network_state.json"
TASK_SUMMARY_PATH = DATA / "task_summary.json"
TAXONOMY_PATH = DATA / "industrial_failure_taxonomy.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _queue_state() -> dict[str, Any]:
    queue = _load_json(QUEUE_PATH, {})
    if not isinstance(queue, dict):
        queue = {}
    for key in ("open_items", "in_progress_items", "done_items", "failed_items"):
        queue.setdefault(key, [])
    return queue


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _existing_signals(queue: dict[str, Any]) -> set[str]:
    signals: set[str] = set()
    for section in ("open_items", "in_progress_items", "done_items", "failed_items"):
        for item in queue.get(section) or []:
            if isinstance(item, dict):
                trigger = item.get("trigger") or {}
                if isinstance(trigger, dict) and trigger.get("signal"):
                    signals.add(str(trigger["signal"]))
    return signals


def _runtime_health_attention() -> bool:
    daemon = _load_json(DAEMON_PATH, {})
    last_result = daemon.get("last_result") or {}
    ai_testing = last_result.get("ai_testing") or {}
    control_layer = _load_json(CONTROL_LAYER_PATH, {})
    autonomy = _load_json(AUTONOMY_PATH, {})
    if str(last_result.get("status") or "").lower() not in {"running", "healthy"}:
        return True
    if str(ai_testing.get("status") or "").lower() == "degraded":
        return True
    if str(control_layer.get("status") or "").lower() not in {"stable", "pass"}:
        return True
    if str(autonomy.get("stage") or "").lower() not in {"stage4_confirmed", "stage5_candidate", "stage5_confirmed"}:
        return True
    return False


def _release_gate_attention() -> bool:
    autonomy = _load_json(AUTONOMY_PATH, {})
    signal_policy = autonomy.get("signal_policy") or {}
    release_gate_count = int(signal_policy.get("release_gate_signal_count") or 0)
    release_ops = _load_json(RELEASE_OPS_PATH, {})
    readiness = release_ops.get("readiness_summary") or {}
    return release_gate_count > 0 or str(readiness.get("status") or "").lower() == "attention"


def _retry_abnormal() -> bool:
    summary = _load_json(TASK_SUMMARY_PATH, {})
    total = int(summary.get("completed_tasks_last_24h") or 0)
    unverified = int(summary.get("unverified_completed_tasks_last_24h") or 0)
    if total <= 0:
        return False
    return unverified / max(1, total) >= 0.2


def _backlog_replenishment_failed() -> bool:
    backlog = _load_json(GOAL_BACKLOG_PATH, {})
    return str(backlog.get("last_replenishment_result") or "").lower() == "replenishment_failed"


def _provider_network_instability() -> bool:
    provider = _load_json(PROVIDER_GATEWAY_PATH, {})
    network = _load_json(NETWORK_STATE_PATH, {})
    provider_status = str(provider.get("status") or provider.get("health") or "").lower()
    network_status = str(network.get("status") or network.get("health") or "").lower()
    return provider_status in {"degraded", "attention", "failed"} or network_status in {"degraded", "attention", "failed"}


def _taxonomy_target_component(category: str) -> str:
    mapping = {
        "artifact_audit_failure": "artifact_registry",
        "verification_failure": "verification_engine",
        "rollback_failure": "release_operations",
        "execution_failure": "factory_task_engine",
        "dispatch_failure": "scheduling_kernel",
        "environment_failure": "runtime_environment",
        "policy_gate_failure": "policy_engine",
        "permission_failure": "privilege_policy",
        "provider_failure": "provider_gateway",
        "flaky_failure": "task_execution_stability",
    }
    return mapping.get(category, "industrial_operations")


def _taxonomy_items() -> list[dict[str, Any]]:
    taxonomy = _load_json(TAXONOMY_PATH, {})
    categories = taxonomy.get("categories") if isinstance(taxonomy, dict) else {}
    if not isinstance(categories, dict):
        return []
    ranked = sorted(
        (
            (str(category), info if isinstance(info, dict) else {})
            for category, info in categories.items()
        ),
        key=lambda pair: int(pair[1].get("count_30d") or 0),
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    for category, info in ranked[:5]:
        strategy = info.get("default_strategy") if isinstance(info, dict) else {}
        verification = list(strategy.get("verification") or ["status refresh"]) if isinstance(strategy, dict) else ["status refresh"]
        items.append({
            "id": f"srg_{stamp}_{category}_{uuid4().hex[:6]}",
            "task_type": "self_repair",
            "category": f"taxonomy:{category}",
            "amplifier": "self_repair_task_generator",
            "repair_category": str(strategy.get("repair_kind") or category),
            "trigger_signal": f"taxonomy:{category}",
            "target_component": _taxonomy_target_component(category),
            "goal": f"Reduce {category.replace('_', ' ')} by applying the taxonomy default repair strategy.",
            "expected_fix_signal": f"{category}_reduced",
            "verification_plan": verification,
            "priority": "high" if int(info.get("count_30d") or 0) >= 50 else "medium",
            "budget_pool": "P1",
            "admission_lane": "repair_first",
            "status": "open",
            "created_at": _utc(),
        })
    return items


def _build_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = _taxonomy_items()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    if _runtime_health_attention():
        items.append({
            "id": f"srg_{stamp}_{uuid4().hex[:6]}",
            "task_type": "self_repair",
            "category": "runtime_health",
            "amplifier": "self_repair_task_generator",
            "repair_category": "runtime",
            "trigger_signal": "runtime_health_attention",
            "target_component": "factory_daemon",
            "goal": "restore runtime health and clear degraded loop behavior",
            "expected_fix_signal": "runtime_health_stable",
            "verification_plan": ["py_compile", "daemon smoke", "status refresh"],
            "priority": "high",
            "budget_pool": "P1",
            "admission_lane": "repair_first",
            "status": "open",
            "created_at": _utc(),
        })
    if _release_gate_attention():
        items.append({
            "id": f"srg_{stamp}_{uuid4().hex[:6]}",
            "task_type": "self_repair",
            "category": "release_gate",
            "repair_category": "release",
            "trigger_signal": "release_gate_signal_gt_0",
            "target_component": "verification_release_gate",
            "goal": "clean up release gate signals and refresh verification evidence",
            "expected_fix_signal": "release_gate_signal_count_zero",
            "verification_plan": ["verification refresh", "artifact audit", "release status refresh"],
            "priority": "high",
            "budget_pool": "P1",
            "admission_lane": "repair_first",
            "status": "open",
            "created_at": _utc(),
        })
    if _retry_abnormal():
        items.append({
            "id": f"srg_{stamp}_{uuid4().hex[:6]}",
            "task_type": "self_repair",
            "category": "retry_policy",
            "repair_category": "retry_policy",
            "trigger_signal": "retry_count_abnormal",
            "target_component": "task_dispatch",
            "goal": "repair retry policy and reduce retry storms",
            "expected_fix_signal": "retry_policy_normalized",
            "verification_plan": ["task summary refresh", "queue pressure check"],
            "priority": "medium",
            "budget_pool": "P1",
            "admission_lane": "repair_first",
            "status": "open",
            "created_at": _utc(),
        })
    if _backlog_replenishment_failed():
        items.append({
            "id": f"srg_{stamp}_{uuid4().hex[:6]}",
            "task_type": "self_repair",
            "category": "backlog_replenishment",
            "repair_category": "replenishment",
            "trigger_signal": "backlog_replenishment_failed",
            "target_component": "goal_backlog_replenisher",
            "goal": "repair backlog replenishment so dispatch candidates keep flowing",
            "expected_fix_signal": "backlog_replenishment_pass",
            "verification_plan": ["goal backlog refresh", "dispatch candidate count check"],
            "priority": "medium",
            "budget_pool": "P1",
            "admission_lane": "repair_first",
            "status": "open",
            "created_at": _utc(),
        })
    if _provider_network_instability():
        items.append({
            "id": f"srg_{stamp}_{uuid4().hex[:6]}",
            "task_type": "self_repair",
            "category": "provider_fallback",
            "repair_category": "fallback",
            "trigger_signal": "provider_auth_or_network_instability",
            "target_component": "provider_gateway",
            "goal": "enable fallback routing for provider auth or network instability",
            "expected_fix_signal": "provider_fallback_ready",
            "verification_plan": ["provider gateway status", "network state refresh"],
            "priority": "medium",
            "budget_pool": "P1",
            "admission_lane": "repair_first",
            "status": "open",
            "created_at": _utc(),
        })
    return items


def run_self_repair_task_generator() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    queue = _queue_state()
    open_items = _dedupe(list(queue.get("open_items") or []))
    existing_signals = _existing_signals(queue)
    created = 0
    for item in _build_items():
        if str(item.get("trigger_signal") or "") in existing_signals:
            continue
        open_items.append(item)
        existing_signals.add(str(item.get("trigger_signal") or ""))
        created += 1
    queue["open_items"] = open_items
    atomic_write_json(QUEUE_PATH, queue)
    record_run(
        "self_repair_task_generator",
        generated_tasks=created,
        entered_execution=0,
        completed_tasks=0,
        trigger_count=1,
        metadata={"queue_path": str(QUEUE_PATH)},
    )
    append_trace(
        "industrial-readiness",
        "generate self-repair tasks",
        "run self_repair_task_generator.py",
        f"created={created}",
        "queue self-repair tasks for execution",
        worker="cheap-worker",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={"queue_path": str(QUEUE_PATH), "created_items": created},
    )
    return {
        "updated_at": _utc(),
        "status": "pass",
        "created_items": created,
        "open_items_total": len(open_items),
        "queue_path": str(QUEUE_PATH),
    }


def main() -> int:
    _ = argparse.ArgumentParser(description="Generate self-repair tasks from live system signals.").parse_args()
    print(json.dumps(run_self_repair_task_generator(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
