from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.provider_gateway import STATE_PATH as PROVIDER_STATE_PATH
from app.risk_engine import DATA, DAEMON_STATE_PATH, RELEASE_OPERATIONS_PATH
from tools.artifact_audit import audit_artifacts, build_reality_dashboard
from tools.goal_backlog_replenisher import build_goal_backlog_plan, record_goal_backlog_result
from tools.goal_registry import list_goals
from tools.io_utils import atomic_write_json
from tools.scheduling_kernel import build_scheduling_snapshot
from tools.verification_engine import run_verification


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


class SafeRepairExecutor:
    supported_actions = {
        "rebuild_priority_tasks",
        "poke_scheduler",
        "soft_restart_dispatcher",
        "switch_provider_fallback",
        "re_run_verification",
        "freeze_release_train",
    }

    def execute(self, risk: dict[str, Any], *, snapshot: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for name in [str(item) for item in (risk.get("allowed_actions") or []) if str(item).strip()]:
            if name not in self.supported_actions:
                actions.append(
                    {
                        "name": name,
                        "result": "skipped",
                        "mode": "unsupported",
                        "detail": {"reason": "no_system_hook"},
                        "started_at": _utc(),
                        "finished_at": _utc(),
                    }
                )
                continue
            if dry_run:
                actions.append(
                    {
                        "name": name,
                        "result": "planned",
                        "mode": "dry_run",
                        "detail": {"reason": "policy_gate_or_non_apply_run"},
                        "started_at": _utc(),
                        "finished_at": _utc(),
                    }
                )
                continue
            action = self._run_action(name, risk=risk, snapshot=snapshot)
            actions.append(action)
            if action.get("result") not in {"success", "simulated"}:
                break
        return actions

    def _run_action(self, name: str, *, risk: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        started_at = _utc()
        try:
            if name == "rebuild_priority_tasks":
                return self._rebuild_priority_tasks(snapshot, started_at=started_at)
            if name == "poke_scheduler":
                return self._poke_scheduler(snapshot, started_at=started_at)
            if name == "soft_restart_dispatcher":
                return self._soft_restart_dispatcher(started_at=started_at)
            if name == "switch_provider_fallback":
                return self._switch_provider_fallback(started_at=started_at)
            if name == "re_run_verification":
                return self._re_run_verification(started_at=started_at)
            if name == "freeze_release_train":
                return self._freeze_release_train(started_at=started_at)
        except Exception as exc:
            return {
                "name": name,
                "result": "failed",
                "mode": "execution",
                "detail": {"error": f"{type(exc).__name__}: {exc}"},
                "started_at": started_at,
                "finished_at": _utc(),
            }
        return {
            "name": name,
            "result": "skipped",
            "mode": "execution",
            "detail": {"reason": "unknown_action"},
            "started_at": started_at,
            "finished_at": _utc(),
        }

    def _rebuild_priority_tasks(self, snapshot: dict[str, Any], *, started_at: str) -> dict[str, Any]:
        plan = build_goal_backlog_plan({"goal_primary": snapshot.get("goal_primary"), "goal_mode": snapshot.get("goal_mode")})
        refreshed = record_goal_backlog_result(plan, dispatched=[])
        return {
            "name": "rebuild_priority_tasks",
            "result": "success",
            "mode": "execution",
            "detail": {
                "goal_id": refreshed.get("goal_id"),
                "goal_health": refreshed.get("goal_health"),
                "dispatch_now_count": refreshed.get("dispatch_now_count"),
                "pending_candidate_count": refreshed.get("pending_candidate_count"),
            },
            "started_at": started_at,
            "finished_at": _utc(),
        }

    def _poke_scheduler(self, snapshot: dict[str, Any], *, started_at: str) -> dict[str, Any]:
        goal_graph_pairs: list[dict[str, Any]] = []
        graph_root = DATA.parent / "factory" / "graphs"
        for goal in list_goals():
            graph_id = str(goal.get("graph_id") or "").strip()
            if not graph_id:
                continue
            graph_path = graph_root / f"{graph_id}.json"
            graph = _load_json(graph_path, {})
            if graph:
                goal_graph_pairs.append({"goal": goal, "graph": graph})
        result = build_scheduling_snapshot(goal_graph_pairs, dispatch_budget=max(1, int(snapshot.get("queue_depth") or 1)), persist=True)
        return {
            "name": "poke_scheduler",
            "result": "success",
            "mode": "execution",
            "detail": {
                "dispatch_budget": result.get("dispatch_budget"),
                "ready_queue": len(result.get("ready_queue") or []),
                "dispatch_order": len(result.get("dispatch_order") or []),
            },
            "started_at": started_at,
            "finished_at": _utc(),
        }

    def _soft_restart_dispatcher(self, *, started_at: str) -> dict[str, Any]:
        daemon_state = _load_json(DAEMON_STATE_PATH, {})
        daemon_state.update({"restart_requested": True, "updated_at": _utc(), "last_error": None, "status": daemon_state.get("status") or "running"})
        atomic_write_json(DAEMON_STATE_PATH, daemon_state)
        return {
            "name": "soft_restart_dispatcher",
            "result": "success",
            "mode": "execution",
            "detail": {"restart_requested": True, "status": daemon_state.get("status")},
            "started_at": started_at,
            "finished_at": _utc(),
        }

    def _switch_provider_fallback(self, *, started_at: str) -> dict[str, Any]:
        provider_state = _load_json(PROVIDER_STATE_PATH, {"updated_at": None, "providers": {}})
        fallback_selected = None
        opened_routes = 0
        for provider_name, provider in (provider_state.get("providers") or {}).items():
            routes = provider.get("candidates") or {}
            if not routes:
                continue
            best_key = None
            best_score: tuple[int, float, str] | None = None
            for candidate_key, route in routes.items():
                failure_count = int(route.get("failure_count") or 0)
                ewma = float(route.get("latency_ewma_ms") or 0.0)
                score = (failure_count, ewma, str(candidate_key))
                if best_score is None or score < best_score:
                    best_score = score
                    best_key = candidate_key
                last_error = str(route.get("last_error") or "").lower()
                if any(token in last_error for token in ("401", "429", "missing scopes", "auth", "unauthorized")):
                    route["circuit_open_until"] = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
                    opened_routes += 1
            if best_key:
                provider["last_selected"] = best_key
                provider["last_success_at"] = provider.get("last_success_at") or _utc()
                fallback_selected = f"{provider_name}:{best_key}"
        provider_state["updated_at"] = _utc()
        atomic_write_json(PROVIDER_STATE_PATH, provider_state)
        if fallback_selected:
            return {
                "name": "switch_provider_fallback",
                "result": "success",
                "mode": "execution",
                "detail": {"fallback_selected": fallback_selected, "opened_routes": opened_routes},
                "started_at": started_at,
                "finished_at": _utc(),
            }
        return {
            "name": "switch_provider_fallback",
            "result": "skipped",
            "mode": "execution",
            "detail": {"reason": "no_provider_routes_available"},
            "started_at": started_at,
            "finished_at": _utc(),
        }

    def _re_run_verification(self, *, started_at: str) -> dict[str, Any]:
        verification = run_verification(refresh_control_layer=False)
        artifacts = audit_artifacts(write_outputs=True)
        dashboard = build_reality_dashboard(write_outputs=True)
        return {
            "name": "re_run_verification",
            "result": "success",
            "mode": "execution",
            "detail": {
                "verification_status": verification.get("status"),
                "artifact_audit_status": artifacts.get("status"),
                "dashboard_status": dashboard.get("status"),
            },
            "started_at": started_at,
            "finished_at": _utc(),
        }

    def _freeze_release_train(self, *, started_at: str) -> dict[str, Any]:
        release_ops = _load_json(RELEASE_OPERATIONS_PATH, {})
        release_ops.setdefault("release_train", {})
        release_ops["release_train"].update({"status": "blocked", "blocked_reason": "risk_branch_freeze", "updated_at": _utc()})
        release_ops.update({"status": "attention", "next_action": "resolve-risk-branch", "updated_at": _utc()})
        atomic_write_json(RELEASE_OPERATIONS_PATH, release_ops)
        return {
            "name": "freeze_release_train",
            "result": "success",
            "mode": "execution",
            "detail": {"release_train_status": "blocked", "blocked_reason": "risk_branch_freeze"},
            "started_at": started_at,
            "finished_at": _utc(),
        }

