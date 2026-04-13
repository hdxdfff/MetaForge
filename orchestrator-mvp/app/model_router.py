from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import settings
from .executor_routing import load_route_experience
from .model_usage import load_usage_snapshot
from .models import StepSpec, TaskRecord, WorkerType


DATA = Path(__file__).resolve().parent.parent / "data"
POLICY_FILE = DATA / "policy.json"


def _load_policy() -> dict[str, Any]:
    if not POLICY_FILE.exists():
        return {}
    try:
        return json.loads(POLICY_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _quota_preserve_mode() -> bool:
    policy = _load_policy()
    return bool(policy.get("quota_preserve_mode", False) or policy.get("premium_frozen", False))


@dataclass(frozen=True)
class RoutedModel:
    provider: str
    model: str
    reason: str


class ModelRouter:
    def _reasoning_route(self, model: str, reason: str) -> RoutedModel:
        return RoutedModel(provider="reasoning", model=model, reason=reason)

    def _strategic_route(self, model: str, reason: str) -> RoutedModel:
        return RoutedModel(provider="openai", model=model, reason=reason)

    def _cheap_route(self, model: str, reason: str) -> RoutedModel:
        return RoutedModel(provider="cheap", model=model, reason=reason)

    def _usage_snapshot(self) -> dict[str, Any]:
        return load_usage_snapshot()

    def _smart_model_routing_enabled(self) -> bool:
        return bool(settings.smart_model_routing_enabled)

    def _task_pressure(self, task: TaskRecord | None) -> dict[str, Any]:
        if task is None:
            return {"escalations": 0, "cheap_blocked": False, "cheap_looping": False, "cheap_pressure": 0.0}
        cheap_looping = task.cheap_lane.repeated_output_count >= max(1, settings.cheap_loop_repeat_threshold)
        cheap_pressure = 0.0
        if task.cheap_lane.blocked:
            cheap_pressure += 1.0
        if cheap_looping:
            cheap_pressure += 0.5
        if task.escalation_count > 0:
            cheap_pressure += min(1.0, task.escalation_count * 0.25)
        if task.cheap_lane.calls_used >= max(1, settings.cheap_max_calls_per_task // 2):
            cheap_pressure += 0.25
        return {
            "escalations": task.escalation_count,
            "cheap_blocked": task.cheap_lane.blocked,
            "cheap_looping": cheap_looping,
            "cheap_pressure": round(cheap_pressure, 2),
        }

    def _route_experience(self, task: TaskRecord | None) -> dict[str, Any]:
        if task is None:
            return {
                "executor_id": None,
                "samples": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "avg_cost_units": 0.0,
                "pressure": 0.0,
            }
        executor_id = str(task.executor_id or "").strip()
        if not executor_id and isinstance(task.executor_route, dict):
            selected = task.executor_route.get("selected")
            if isinstance(selected, dict):
                executor_id = str(selected.get("executor_id") or "").strip()
        if not executor_id:
            return {
                "executor_id": None,
                "samples": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "avg_cost_units": 0.0,
                "pressure": 0.0,
            }
        snapshot = load_route_experience()
        bucket = dict((snapshot.get("executors") or {}).get(executor_id) or {})
        samples = int(bucket.get("samples") or 0)
        success_rate = float(bucket.get("success_rate") or 0.0)
        avg_latency_ms = float(bucket.get("avg_latency_ms") or 0.0)
        avg_cost_units = float(bucket.get("avg_cost_units") or 0.0)
        pressure = 0.0
        if samples:
            if success_rate < 0.55:
                pressure += 2.0
            elif success_rate < 0.75:
                pressure += 1.0
            elif success_rate > 0.9:
                pressure -= 0.5
            if avg_latency_ms > 30000:
                pressure += 1.0
            elif avg_latency_ms > 15000:
                pressure += 0.5
            if avg_cost_units > 6.0:
                pressure += 0.5
            elif avg_cost_units < 2.0 and success_rate > 0.85:
                pressure -= 0.5
        return {
            "executor_id": executor_id,
            "samples": samples,
            "success_rate": round(success_rate, 3),
            "avg_latency_ms": round(avg_latency_ms, 2),
            "avg_cost_units": round(avg_cost_units, 3),
            "pressure": round(pressure, 2),
        }

    def _needs_reasoning_worker(self, step: StepSpec, task: TaskRecord | None = None) -> bool:
        if task is not None:
            task_type = str(getattr(task, "task_type", "") or "").strip().lower()
            execution_mode_value = getattr(task, "execution_mode", "")
            execution_mode = str(getattr(execution_mode_value, "value", execution_mode_value) or "").strip().lower()
            if execution_mode in {"research", "governance"} and task_type in {
                "artifact_audit",
                "json_fix",
                "manifest_patch",
                "report_refresh",
                "doc_patch",
            }:
                return True
        if step.assigned_role and step.assigned_role.value == "architect":
            return True
        corpus = " ".join(
            part
            for part in [step.title, step.instructions, step.phase or "", " ".join(step.acceptance_criteria)]
            if part
        ).lower()
        high_risk_markers = (
            "architecture",
            "migration",
            "security",
            "permission",
            "rollback",
            "incident",
            "regression",
            "root cause",
            "cross-project",
            "scheduler",
            "routing",
            "policy",
        )
        return any(marker in corpus for marker in high_risk_markers)

    def _needs_strong_worker(self, step: StepSpec, task: TaskRecord | None, usage: dict[str, Any]) -> bool:
        if not self._smart_model_routing_enabled():
            return False
        if not bool(usage.get("strong_allowed", True)):
            return False
        corpus = " ".join(
            part
            for part in [step.title, step.instructions, step.phase or "", " ".join(step.acceptance_criteria), step.command or ""]
            if part
        ).lower()
        strategic_markers = (
            "architecture",
            "migration",
            "security",
            "permission",
            "rollback",
            "incident",
            "regression",
            "root cause",
            "cross-project",
            "scheduler",
            "routing",
            "policy",
            "blocked",
            "deadlock",
            "triage",
        )
        usage_pressure = max(
            float(usage.get("reasoning_pressure", 0.0) or 0.0),
            float(usage.get("strong_pressure", 0.0) or 0.0),
        )
        task_pressure = self._task_pressure(task)
        return (
            any(marker in corpus for marker in strategic_markers)
            or (step.assigned_role is not None and step.assigned_role.value == "architect")
            or task_pressure["cheap_blocked"]
            or task_pressure["cheap_looping"]
            or task_pressure["escalations"] > 0
            or usage_pressure >= 0.95
        )

    def route_step(self, step: StepSpec, task: TaskRecord | None = None) -> RoutedModel:
        quota_preserve = _quota_preserve_mode()
        usage = self._usage_snapshot()
        task_pressure = self._task_pressure(task)
        route_experience = self._route_experience(task)
        task_type = str(getattr(task, "task_type", "") or "").strip().lower() if task is not None else ""
        execution_mode_value = getattr(task, "execution_mode", "") if task is not None else ""
        execution_mode = str(getattr(execution_mode_value, "value", execution_mode_value) or "").strip().lower()
        audit_work = execution_mode in {"research", "governance"} and task_type in {
            "artifact_audit",
            "json_fix",
            "manifest_patch",
            "report_refresh",
            "doc_patch",
        }
        experience_pressure = float(route_experience.get("pressure") or 0.0)
        experience_note = ""
        if route_experience.get("executor_id"):
            experience_note = (
                f" Historical executor '{route_experience['executor_id']}' history "
                f"shows success_rate={route_experience['success_rate']}, "
                f"latency={route_experience['avg_latency_ms']}ms, "
                f"cost={route_experience['avg_cost_units']}."
            )
        if step.worker == WorkerType.planner:
            if experience_pressure >= 1.5 and usage.get("strong_allowed", True):
                if step.assigned_role and step.assigned_role.value == "architect":
                    return self._strategic_route(
                        settings.architect_model,
                        "Planner route is experience-throttled, so use the strategic lane to compensate for a weak executor history." + experience_note,
                    )
                return self._reasoning_route(
                    settings.reasoning_planner_model,
                    "Planner route is experience-throttled, so use the reasoning lane to reduce downstream risk." + experience_note,
                )
            if step.assigned_role and step.assigned_role.value == "architect":
                if quota_preserve or task_pressure["cheap_blocked"]:
                    if usage.get("reasoning_allowed", True):
                        return self._reasoning_route(
                            settings.reasoning_planner_model,
                            "Route strategic planning to the reasoning lane because premium quota is preserved or the cheap lane is blocked.",
                        )
                    return self._cheap_route(
                        settings.cheap_summary_model,
                        "Strategic planning is pressure-limited; fall back to the cheap summary lane.",
                    )
                if usage.get("strong_allowed", True):
                    return self._strategic_route(
                        settings.architect_model,
                        "Architecture and strategic decomposition stay on the strategic lane when strong quota is available.",
                    )
                if usage.get("reasoning_allowed", True):
                    return self._reasoning_route(
                        settings.reasoning_planner_model,
                        "Strong quota is throttled, so route strategic planning to the reasoning lane.",
                    )
                return self._cheap_route(
                    settings.cheap_summary_model,
                    "All remote lanes are throttled, so fall back to the cheap planning lane.",
                )
            if not usage.get("reasoning_allowed", True):
                if usage.get("strong_allowed", True) and not quota_preserve:
                    return self._strategic_route(
                        settings.planner_model,
                        "Reasoning quota is throttled; use the strategic lane for planner supervision.",
                    )
                return self._cheap_route(
                    settings.cheap_summary_model,
                    "Reasoning quota is throttled and strong quota is unavailable, so use the cheap planner lane.",
                )
            return self._reasoning_route(
                settings.reasoning_planner_model,
                "Route default planning, decomposition, and supervision to the reasoning lane unless smart routing has stronger quota pressure." + experience_note,
            )
        if step.worker == WorkerType.coder:
            if audit_work:
                return self._strategic_route(
                    settings.planner_escalation_model,
                    "Route research/governance audit work to the strategic lane so it can return a concrete implementation or patch plan instead of a cheap summary.",
                )
            if experience_pressure >= 1.5 and usage.get("strong_allowed", True):
                return self._strategic_route(
                    settings.expensive_coder_model,
                    "Coder route is experience-throttled, so use the strongest available model to compensate for historically weak execution history." + experience_note,
                )
            if experience_pressure >= 0.75 and usage.get("reasoning_allowed", True):
                return self._reasoning_route(
                    settings.reasoning_coder_model,
                    "Coder route is moderately experience-throttled, so route to the reasoning lane for more resilient planning." + experience_note,
                )
            if self._needs_strong_worker(step, task, usage):
                if usage.get("strong_allowed", True):
                    return self._strategic_route(
                        settings.expensive_coder_model,
                        "Coder step is strategic or cheap-lane pressure is high, so use the strongest available model on demand.",
                    )
                if usage.get("reasoning_allowed", True):
                    return self._reasoning_route(
                        settings.reasoning_coder_model,
                        "Coder step needs deeper diagnosis, but the strong lane is throttled, so use reasoning instead.",
                    )
                return self._cheap_route(
                    settings.cheap_coder_model,
                    "Coder step is pressure-limited, so fall back to the cheap lane.",
                )
            if not self._needs_reasoning_worker(step, task):
                return self._cheap_route(
                    settings.cheap_coder_model,
                    "Default implementation work stays on the cheap lane; escalate only when the step is architectural, risky, blocked, or quota pressure rises.",
                )
            if not usage.get("reasoning_allowed", True):
                return self._cheap_route(
                    settings.cheap_coder_model,
                    "Reasoning quota is throttled, so fall back to the cheap coding lane.",
                )
            return self._reasoning_route(
                settings.reasoning_coder_model,
                "Route implementation work to the reasoning lane only when the step is architectural, high-risk, or likely to need deeper diagnosis and strong quota is not warranted." + experience_note,
            )
        if step.worker == WorkerType.reviewer:
            if audit_work:
                return self._strategic_route(
                    settings.planner_escalation_model,
                    "Route research/governance audit review to the strategic lane so it can return a concrete review decision instead of a cheap summary.",
                )
            if experience_pressure >= 1.5 and usage.get("strong_allowed", True):
                return self._strategic_route(
                    settings.planner_escalation_model,
                    "Review route is experience-throttled, so use the strongest available review model to compensate for weak executor history." + experience_note,
                )
            if experience_pressure >= 0.75 and usage.get("reasoning_allowed", True):
                return self._reasoning_route(
                    settings.reasoning_review_model,
                    "Review route is moderately experience-throttled, so route to the reasoning lane for more robust review." + experience_note,
                )
            if self._needs_strong_worker(step, task, usage):
                if usage.get("strong_allowed", True):
                    return self._strategic_route(
                        settings.planner_escalation_model,
                        "Review step is strategic or the cheap lane is under pressure, so use the strongest available review model on demand.",
                    )
                if usage.get("reasoning_allowed", True):
                    return self._reasoning_route(
                        settings.reasoning_review_model,
                        "Review step needs deeper diagnosis, but the strong lane is throttled, so use reasoning instead.",
                    )
                return self._cheap_route(
                    settings.cheap_review_model,
                    "Review step is pressure-limited, so fall back to the cheap review lane.",
                )
            if not self._needs_reasoning_worker(step, task):
                return self._cheap_route(
                    settings.cheap_review_model,
                    "Default review and summarization stay on the cheap lane; escalate only for regression-heavy or architectural review.",
                )
            if not usage.get("reasoning_allowed", True):
                return self._cheap_route(
                    settings.cheap_review_model,
                    "Reasoning quota is throttled, so fall back to the cheap review lane.",
                )
            return self._reasoning_route(
                settings.reasoning_review_model,
                "Route review to the reasoning lane only when the step is architectural, risky, or likely to require deeper diagnosis and strong quota is not warranted." + experience_note,
            )
        if step.worker == WorkerType.publisher:
            return RoutedModel(
                provider="runtime",
                model=settings.default_publish_check_model,
                reason="Publishing is local runtime work; only a cheap model is needed for summaries and pre-push checks.",
            )
        if step.worker == WorkerType.browser:
            return RoutedModel(
                provider="runtime",
                model=settings.default_simple_task_model,
                reason="Browser bridge execution stays on the runtime lane by default.",
            )
        if step.worker in {WorkerType.shell, WorkerType.docker}:
            return RoutedModel(
                provider="runtime",
                model=settings.default_simple_task_model,
                reason="Simple execution and summarization should stay on the cheap lane by default.",
            )
        return RoutedModel(provider="cheap", model=settings.default_simple_task_model, reason="Default cheap route.")

    def planner_escalation(self) -> RoutedModel:
        usage = self._usage_snapshot()
        if _quota_preserve_mode() or not usage.get("strong_allowed", True):
            if usage.get("reasoning_allowed", True):
                return self._reasoning_route(
                    settings.reasoning_review_model,
                    "Quota-preserve mode or strong-model throttling freezes strategic escalation; route escalation analysis to the reasoning lane instead of the cheap lane.",
                )
            return self._cheap_route(
                settings.cheap_review_model,
                "All remote lanes are throttled, so use the cheap review lane for escalation analysis.",
            )
        return self._strategic_route(
            settings.planner_escalation_model,
            "Escalate only for deadlocks, high-risk changes, or contradictory worker outputs.",
        )
