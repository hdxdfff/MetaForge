from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json
from uuid import uuid4

from tools.capability_library import match_local_capability
ROOT = Path(__file__).resolve().parent.parent
GOALS = ROOT / "factory" / "goals" / "goal_registry.json"

ACTIVE_STATUSES = {"pending", "planned", "running"}
TERMINAL_STATUSES = {"completed", "archived", "failed", "cancelled"}
PAUSED_STATUSES = {"on_hold"}

GOAL_VALUE_BY_TYPE = {
    "build_platform": 0.92,
    "build_product": 0.84,
    "verify_platforms": 0.78,
    "experiment": 0.7,
    "architecture_upgrade": 0.88,
    "capability_upgrade": 0.82,
    "verification_upgrade": 0.76,
    "production_instance": 0.8,
}

GOAL_COST_BY_TYPE = {
    "build_platform": 0.64,
    "build_product": 0.48,
    "verify_platforms": 0.24,
    "experiment": 0.36,
    "architecture_upgrade": 0.42,
    "capability_upgrade": 0.38,
    "verification_upgrade": 0.28,
    "production_instance": 0.5,
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(high, float(value))), 4)


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


class GoalEngine:
    def __init__(self, path: Path = GOALS) -> None:
        self.path = path
        self._cached_signature: tuple[int, int] | None = None
        self._cached_goals: list[dict[str, Any]] | None = None

    def _path_signature(self) -> tuple[int, int] | None:
        if not self.path.exists():
            return None
        stat = self.path.stat()
        return stat.st_mtime_ns, stat.st_size

    def _load_goals_cached(self) -> list[dict[str, Any]]:
        signature = self._path_signature()
        if signature is not None and self._cached_signature == signature and self._cached_goals is not None:
            return self._cached_goals
        if signature is None:
            self._cached_signature = None
            self._cached_goals = []
            return self._cached_goals
        raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        changed = False
        goals: list[dict[str, Any]] = []
        for item in raw:
            normalized, item_changed = self._normalize_goal(item)
            goals.append(normalized)
            changed = changed or item_changed
        self._cached_signature = signature
        self._cached_goals = goals
        if changed:
            self.save_goals(goals)
        return self._cached_goals or []

    def load_goals(self) -> list[dict[str, Any]]:
        return deepcopy(self._load_goals_cached())

    def _goal_timestamp(self, goal: dict[str, Any]) -> datetime:
        parsed = _parse_time(str(goal.get("updated_at") or goal.get("created_at") or "")) or _parse_time(str(goal.get("created_at") or ""))
        return parsed or datetime.fromtimestamp(0, tz=timezone.utc)

    def _merge_goals_for_save(self, goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.path.exists():
            return deepcopy(goals)
        try:
            raw_existing = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            return deepcopy(goals)
        existing_goals: list[dict[str, Any]] = []
        for item in raw_existing:
            normalized, _ = self._normalize_goal(item)
            existing_goals.append(normalized)
        incoming_by_id = {
            str(goal.get("goal_id") or ""): deepcopy(goal)
            for goal in goals
            if goal.get("goal_id")
        }
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for existing in existing_goals:
            goal_id = str(existing.get("goal_id") or "")
            if not goal_id:
                merged.append(existing)
                continue
            incoming = incoming_by_id.get(goal_id)
            if incoming is None:
                merged.append(existing)
                seen.add(goal_id)
                continue
            chosen = incoming if self._goal_timestamp(incoming) >= self._goal_timestamp(existing) else existing
            merged.append(chosen)
            seen.add(goal_id)
        for goal in goals:
            goal_id = str(goal.get("goal_id") or "")
            if goal_id and goal_id in seen:
                continue
            merged.append(deepcopy(goal))
        return merged

    def save_goals(self, goals: list[dict[str, Any]]) -> None:
        merged_goals = self._merge_goals_for_save(goals)
        atomic_write_json(self.path, merged_goals)
        self._cached_goals = deepcopy(merged_goals)
        self._cached_signature = self._path_signature()

    def create_goal(
        self,
        target: str,
        *,
        goal_type: str = "build_platform",
        notes: str = "",
        lane: str = "mainline",
        lane_role: str | None = None,
        branch_name: str | None = None,
        branch_context_ref: str | None = None,
        assigned_department: str | None = None,
        source_session: str | None = None,
        shares_mainline_context: bool = True,
        upstream_context_refs: list[str] | None = None,
        deadline: str | None = None,
        reward: float | None = None,
        cost: float | None = None,
        parent_goal: str | None = None,
        derived_from: dict[str, Any] | None = None,
        success_criteria: list[str] | None = None,
        tags: list[str] | None = None,
        decomposition: list[dict[str, Any]] | None = None,
        scoring: dict[str, Any] | None = None,
        status: str = "pending",
        **extra: Any,
    ) -> dict[str, Any]:
        goals = self.load_goals()
        created_at = _utc()
        capability_plan = self._derive_capability_plan(target, goal_type)
        goal = {
            "goal_id": f"goal_{uuid4().hex[:10]}",
            "type": goal_type,
            "target": target,
            "notes": notes,
            "lane": lane,
            "lane_role": lane_role or ("architecture_mainline" if lane == "mainline" else "capability_branch"),
            "branch_name": branch_name,
            "branch_context_ref": branch_context_ref,
            "assigned_department": assigned_department,
            "source_session": source_session,
            "shares_mainline_context": shares_mainline_context,
            "upstream_context_refs": list(upstream_context_refs or []),
            "status": status,
            "created_at": created_at,
            "updated_at": created_at,
            "graph_id": None,
            "task_ids": [],
            "parent_goal": parent_goal,
            "child_goal_ids": [],
            "goal_class": self._goal_class(goal_type),
            "deadline": deadline,
            "reward": reward,
            "cost": cost,
            "success_criteria": list(success_criteria or self._default_success_criteria(goal_type, target)),
            "tags": list(tags or self._default_tags(goal_type, target, lane)),
            "decomposition": deepcopy(decomposition) if decomposition is not None else self._decompose_goal(target, goal_type),
            "reflection": [],
            "evaluation": {
                "last_reviewed_at": None,
                "completion_ratio": 0.0,
                "blockers": [],
            },
            "derived_from": deepcopy(derived_from) if derived_from else {},
            "metadata": {"capability_plan": capability_plan},
            "scoring": {},
        }
        metadata = goal["metadata"]
        metadata.update(extra.pop("metadata", {}))
        for key, value in extra.items():
            goal[key] = value
        goal["scoring"] = self._score_goal(goal, scoring=scoring)
        goal["priority_score"] = goal["scoring"]["priority_score"]
        goal["priority_band"] = goal["scoring"]["priority_band"]
        goal["lifecycle"] = {
            "stage": self._status_to_stage(goal["status"]),
            "history": [
                {
                    "at": created_at,
                    "from": None,
                    "to": goal["status"],
                    "reason": "goal-created",
                }
            ],
        }
        goals.append(goal)
        if parent_goal:
            parent = next((item for item in goals if item.get("goal_id") == parent_goal), None)
            if parent is not None:
                parent.setdefault("child_goal_ids", [])
                if goal["goal_id"] not in parent["child_goal_ids"]:
                    parent["child_goal_ids"].append(goal["goal_id"])
                    parent["updated_at"] = created_at
                    parent["scoring"] = self._score_goal(parent)
                    parent["priority_score"] = parent["scoring"]["priority_score"]
                    parent["priority_band"] = parent["scoring"]["priority_band"]
        self.save_goals(goals)
        return goal

    def list_goals(self, *, status: str | None = None) -> list[dict[str, Any]]:
        goals = self.load_goals()
        if status is None:
            return goals
        return [goal for goal in goals if goal.get("status") == status]

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        goal = next((item for item in self.load_goals() if item.get("goal_id") == goal_id), None)
        if goal is None:
            raise KeyError("Goal not found")
        return goal

    def update_goal(self, goal_id: str, **updates: Any) -> dict[str, Any]:
        goals = self.load_goals()
        for goal in goals:
            if goal.get("goal_id") != goal_id:
                continue
            previous_status = goal.get("status")
            scoring_override = updates.pop("scoring", None)
            reflection_update = updates.pop("reflection_entry", None)
            blockers = updates.pop("blockers", None)
            status_reason = updates.pop("status_reason", None)
            metadata_update = updates.pop("metadata", None)
            changed = False
            for key, value in updates.items():
                if value is None:
                    continue
                if goal.get(key) != value:
                    goal[key] = value
                    changed = True
            if metadata_update:
                goal.setdefault("metadata", {})
                for key, value in metadata_update.items():
                    if goal["metadata"].get(key) != value:
                        goal["metadata"][key] = value
                        changed = True
            if blockers is not None:
                goal.setdefault("evaluation", {})
                blocker_list = list(blockers)
                if goal["evaluation"].get("blockers") != blocker_list:
                    goal["evaluation"]["blockers"] = blocker_list
                    changed = True
            if reflection_update:
                goal.setdefault("reflection", [])
                goal["reflection"].append(reflection_update)
                goal.setdefault("evaluation", {})
                goal["evaluation"]["last_reviewed_at"] = reflection_update.get("at") or _utc()
                changed = True
            if not changed and scoring_override is None:
                return goal
            goal["updated_at"] = _utc()
            self._refresh_lifecycle(goal, previous_status, goal.get("status"), status_reason)
            goal["evaluation"] = self._rebuild_evaluation(goal)
            goal["scoring"] = self._score_goal(goal, scoring=scoring_override)
            goal["priority_score"] = goal["scoring"]["priority_score"]
            goal["priority_band"] = goal["scoring"]["priority_band"]
            self.save_goals(goals)
            return goal
        raise KeyError("Goal not found")

    def reflect_goal(
        self,
        goal_id: str,
        *,
        success: bool,
        summary: str,
        blockers: list[str] | None = None,
        next_target: str | None = None,
        next_goal_type: str | None = None,
    ) -> dict[str, Any]:
        reflection_entry = {
            "at": _utc(),
            "success": bool(success),
            "summary": summary,
            "blockers": list(blockers or []),
            "next_target": next_target,
            "next_goal_type": next_goal_type,
        }
        status = "completed" if success else "failed"
        goal = self.update_goal(
            goal_id,
            status=status,
            blockers=blockers or [],
            reflection_entry=reflection_entry,
            status_reason="goal-reflection",
        )
        follow_up = None
        if next_target:
            follow_up = self.create_goal(
                next_target,
                goal_type=next_goal_type or goal.get("type") or "build_product",
                notes=f"Follow-up generated by reflection on {goal_id}.",
                parent_goal=goal_id,
                derived_from={"reflection_goal_id": goal_id},
            )
        return {"goal": goal, "follow_up": follow_up}

    def rank_goals(
        self,
        goals: list[dict[str, Any]] | None = None,
        *,
        statuses: set[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        items = list(goals if goals is not None else self._load_goals_cached())
        if statuses is not None:
            items = [item for item in items if item.get("status") in statuses]
        items.sort(
            key=lambda goal: (
                float(goal.get("priority_score", 0.0) or 0.0),
                1 if goal.get("status") == "running" else 0,
                _parse_time(goal.get("updated_at") or goal.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        return items[:limit] if limit is not None else items

    def select_goal(self, *, statuses: set[str] | None = None) -> dict[str, Any] | None:
        ranked = self.rank_goals(statuses=statuses or ACTIVE_STATUSES, limit=1)
        return ranked[0] if ranked else None

    def goal_report(self, *, top_n: int = 8) -> dict[str, Any]:
        goals = self.load_goals()
        counts: dict[str, int] = {}
        for goal in goals:
            status = str(goal.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        ranked = self.rank_goals(goals, statuses=ACTIVE_STATUSES, limit=top_n)
        return {
            "updated_at": _utc(),
            "goal_count": len(goals),
            "status_counts": counts,
            "selected_goal": self.select_goal(statuses=ACTIVE_STATUSES),
            "top_goals": ranked,
        }

    def _normalize_goal(self, goal: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        item = deepcopy(goal)
        changed = False
        item.setdefault("goal_id", f"goal_{uuid4().hex[:10]}")
        item.setdefault("type", "build_platform")
        item.setdefault("target", "")
        item.setdefault("notes", "")
        item.setdefault("lane", "mainline")
        item.setdefault("lane_role", "architecture_mainline")
        item.setdefault("branch_name", None)
        item.setdefault("branch_context_ref", None)
        item.setdefault("assigned_department", None)
        item.setdefault("source_session", None)
        item.setdefault("shares_mainline_context", True)
        item.setdefault("upstream_context_refs", [])
        item.setdefault("graph_id", None)
        item.setdefault("task_ids", [])
        item.setdefault("parent_goal", None)
        item.setdefault("child_goal_ids", [])
        item.setdefault("goal_class", self._goal_class(str(item.get("type") or "")))
        item.setdefault("deadline", None)
        item.setdefault("reward", None)
        item.setdefault("cost", None)
        item.setdefault("success_criteria", self._default_success_criteria(str(item.get("type") or ""), str(item.get("target") or "")))
        item.setdefault("tags", self._default_tags(str(item.get("type") or ""), str(item.get("target") or ""), str(item.get("lane") or "")))
        item.setdefault("decomposition", self._decompose_goal(str(item.get("target") or ""), str(item.get("type") or "")))
        item.setdefault("reflection", [])
        item.setdefault("derived_from", {})
        item.setdefault("metadata", {})
        if "capability_plan" not in item["metadata"]:
            item["metadata"]["capability_plan"] = self._derive_capability_plan(str(item.get("target") or ""), str(item.get("type") or ""))
            changed = True
        item.setdefault("created_at", _utc())
        item.setdefault("updated_at", item["created_at"])
        item.setdefault("status", "pending")
        lifecycle = item.get("lifecycle")
        if not isinstance(lifecycle, dict):
            item["lifecycle"] = {
                "stage": self._status_to_stage(str(item.get("status") or "pending")),
                "history": [
                    {
                        "at": item.get("created_at"),
                        "from": None,
                        "to": item.get("status"),
                        "reason": "legacy-import",
                    }
                ],
            }
            changed = True
        else:
            lifecycle.setdefault("stage", self._status_to_stage(str(item.get("status") or "pending")))
            lifecycle.setdefault("history", [])
        item["evaluation"] = self._rebuild_evaluation(item)
        scoring = self._score_goal(item, scoring=item.get("scoring"))
        if item.get("scoring") != scoring:
            item["scoring"] = scoring
            changed = True
        if item.get("priority_score") != scoring["priority_score"]:
            item["priority_score"] = scoring["priority_score"]
            changed = True
        if item.get("priority_band") != scoring["priority_band"]:
            item["priority_band"] = scoring["priority_band"]
            changed = True
        return item, changed

    def _rebuild_evaluation(self, goal: dict[str, Any]) -> dict[str, Any]:
        decomposition = goal.get("decomposition") or []
        completed = sum(1 for item in decomposition if item.get("status") == "completed")
        total = len(decomposition)
        ratio = round((completed / total), 4) if total else 0.0
        existing = goal.get("evaluation") if isinstance(goal.get("evaluation"), dict) else {}
        return {
            "last_reviewed_at": existing.get("last_reviewed_at"),
            "completion_ratio": ratio if goal.get("status") not in TERMINAL_STATUSES else 1.0 if goal.get("status") == "completed" else ratio,
            "blockers": list(existing.get("blockers") or []),
        }

    def _refresh_lifecycle(self, goal: dict[str, Any], previous_status: str | None, current_status: str | None, reason: str | None) -> None:
        lifecycle = goal.setdefault("lifecycle", {"stage": self._status_to_stage(current_status or "pending"), "history": []})
        lifecycle["stage"] = self._status_to_stage(current_status or "pending")
        if previous_status != current_status:
            lifecycle.setdefault("history", []).append(
                {
                    "at": goal.get("updated_at") or _utc(),
                    "from": previous_status,
                    "to": current_status,
                    "reason": reason or "status-update",
                }
            )

    def _score_goal(self, goal: dict[str, Any], scoring: dict[str, Any] | None = None) -> dict[str, Any]:
        scoring = deepcopy(scoring) if scoring else {}
        goal_type = str(goal.get("type") or "build_platform")
        status = str(goal.get("status") or "pending")
        value = float(scoring.get("value", GOAL_VALUE_BY_TYPE.get(goal_type, 0.72)))
        urgency = float(scoring.get("urgency", self._urgency_score(goal)))
        success = float(scoring.get("success", self._success_score(goal)))
        cost = float(scoring.get("cost", goal.get("cost") if goal.get("cost") is not None else GOAL_COST_BY_TYPE.get(goal_type, 0.4)))
        reward = float(scoring.get("reward", goal.get("reward") if goal.get("reward") is not None else value))
        if status == "running":
            urgency += 0.08
        elif status == "planned":
            urgency += 0.04
        elif status in TERMINAL_STATUSES:
            urgency = 0.0
            reward = 0.0 if status != "completed" else reward
        elif status in PAUSED_STATUSES:
            urgency -= 0.12
        value = _clamp(value)
        urgency = _clamp(urgency)
        success = _clamp(success)
        cost = _clamp(max(0.05, cost))
        reward = _clamp(reward)
        blended_value = value * 0.35 + urgency * 0.3 + success * 0.2 + reward * 0.15
        execution_penalty = max(0.2, 1.0 - cost * 0.6)
        priority_score = _clamp(blended_value * execution_penalty)
        if priority_score >= 0.7:
            band = "critical"
        elif priority_score >= 0.45:
            band = "high"
        elif priority_score >= 0.25:
            band = "medium"
        else:
            band = "low"
        return {
            "value": value,
            "urgency": urgency,
            "success": success,
            "cost": cost,
            "reward": reward,
            "priority_score": priority_score,
            "priority_band": band,
        }

    def _urgency_score(self, goal: dict[str, Any]) -> float:
        deadline = _parse_time(goal.get("deadline"))
        if deadline is None:
            base = 0.58 if goal.get("status") in ACTIVE_STATUSES else 0.44
        else:
            now = datetime.now(timezone.utc)
            delta_hours = max(0.0, (deadline - now).total_seconds() / 3600.0)
            if delta_hours <= 6:
                base = 0.98
            elif delta_hours <= 24:
                base = 0.86
            elif delta_hours <= 72:
                base = 0.72
            else:
                base = 0.55
        notes = str(goal.get("notes") or "").lower()
        target = str(goal.get("target") or "").lower()
        if any(token in target or token in notes for token in ("bug", "failure", "blocked", "urgent", "degraded", "release")):
            base += 0.12
        return base

    def _success_score(self, goal: dict[str, Any]) -> float:
        base = 0.7
        target = str(goal.get("target") or "").lower()
        notes = str(goal.get("notes") or "").lower()
        if goal.get("type") == "verify_platforms":
            base = 0.92
        elif goal.get("type") == "experiment":
            base = 0.66
        elif "auto-generated" in notes:
            base -= 0.04
        if any(token in target for token in ("refactor", "upgrade", "architecture")):
            base -= 0.05
        if goal.get("assigned_department") or goal.get("lane_role"):
            base += 0.03
        return base

    def _goal_class(self, goal_type: str) -> str:
        if goal_type in {"build_platform", "architecture_upgrade"}:
            return "strategic"
        if goal_type in {"build_product", "capability_upgrade", "production_instance"}:
            return "operational"
        return "micro"

    def _status_to_stage(self, status: str) -> str:
        mapping = {
            "pending": "created",
            "planned": "planned",
            "running": "executing",
            "completed": "completed",
            "archived": "archived",
            "failed": "failed",
            "cancelled": "archived",
            "on_hold": "paused",
        }
        return mapping.get(status, "created")

    def _default_success_criteria(self, goal_type: str, target: str) -> list[str]:
        criteria = [f"Target is materially advanced: {target}"]
        if goal_type in {"build_platform", "build_product", "architecture_upgrade", "capability_upgrade"}:
            criteria.append("Task graph or implementation plan is generated and executable.")
        if goal_type == "verify_platforms":
            criteria.append("Verification sweep completes with actionable output.")
        if goal_type == "experiment":
            criteria.append("Experiment result is evaluated and adoption decision is recorded.")
        return criteria

    def _default_tags(self, goal_type: str, target: str, lane: str) -> list[str]:
        tags = [goal_type, lane]
        target_lower = target.lower()
        for token in ("scheduler", "prompt", "platform", "verification", "release", "architecture", "capability", "patch"):
            if token in target_lower:
                tags.append(token)
        return list(dict.fromkeys(tags))

    def _decompose_goal(self, target: str, goal_type: str) -> list[dict[str, Any]]:
        blueprint: list[str]
        target_label = target.strip() or "goal"
        if goal_type == "verify_platforms":
            blueprint = [
                "Define verification scope",
                "Run verification sweep",
                "Triage findings",
                "Close or escalate issues",
            ]
        elif goal_type == "experiment":
            blueprint = [
                "Frame hypothesis",
                "Run experiment",
                "Evaluate result",
                "Decide adoption",
            ]
        elif goal_type in {"build_platform", "architecture_upgrade"}:
            blueprint = [
                "Define architecture",
                "Plan execution graph",
                "Implement enabling work",
                "Verify system health",
            ]
        else:
            blueprint = [
                "Clarify deliverable",
                "Plan implementation",
                "Execute work",
                "Verify outcome",
            ]
        return [
            {
                "id": f"{_slug(target_label) or 'goal'}_{idx}",
                "title": title,
                "status": "pending",
            }
            for idx, title in enumerate(blueprint, start=1)
        ]

    def _derive_capability_plan(self, target: str, goal_type: str) -> dict[str, Any]:
        matched = match_local_capability(target, goal_type=goal_type)
        selected = matched.get("selected") or {}
        return {
            "selected_capability_id": selected.get("capability_id"),
            "source": matched.get("source"),
            "recommended_tools": list(selected.get("tools", [])),
            "success_conditions": list(selected.get("success_conditions", [])),
            "step_count": len(selected.get("steps", []) or []),
            "matches": [
                {
                    "capability_id": item.get("capability_id"),
                    "score": item.get("score"),
                }
                for item in matched.get("matches", [])[:5]
            ],
        }
ENGINE = GoalEngine()




