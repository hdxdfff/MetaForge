from __future__ import annotations

from dataclasses import dataclass

from .config import settings
from .models import TaskRecord


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str = ""


class CheapLaneGovernor:
    def authorize(self, task: TaskRecord, planned_chars: int) -> BudgetDecision:
        if task.cheap_lane.blocked:
            return BudgetDecision(False, task.cheap_lane.block_reason or "Cheap lane already blocked.")
        if task.cheap_lane.calls_used >= settings.cheap_max_calls_per_task:
            task.cheap_lane.blocked = True
            task.cheap_lane.block_reason = "Cheap model call limit reached."
            return BudgetDecision(False, task.cheap_lane.block_reason)
        if task.cheap_lane.chars_used + planned_chars > settings.cheap_max_chars_per_task:
            task.cheap_lane.blocked = True
            task.cheap_lane.block_reason = "Cheap model token budget reached."
            return BudgetDecision(False, task.cheap_lane.block_reason)
        return BudgetDecision(True)

    def record_usage(self, task: TaskRecord, total_chars: int) -> None:
        task.cheap_lane.calls_used += 1
        task.cheap_lane.chars_used += max(0, total_chars)

    def record_output(self, task: TaskRecord, worker_name: str, output: str) -> bool:
        fingerprint = self._fingerprint(output)
        if task.cheap_lane.last_worker == worker_name and task.cheap_lane.last_output_fingerprint == fingerprint:
            task.cheap_lane.repeated_output_count += 1
        else:
            task.cheap_lane.repeated_output_count = 0
        task.cheap_lane.last_worker = worker_name
        task.cheap_lane.last_output_fingerprint = fingerprint
        if task.cheap_lane.repeated_output_count >= settings.cheap_loop_repeat_threshold:
            task.cheap_lane.blocked = True
            task.cheap_lane.block_reason = "Cheap worker appears to be looping with repeated output."
            return True
        return False

    def can_escalate(self, task: TaskRecord) -> bool:
        return settings.core_escalation_on_cheap_failure and task.escalation_count < settings.max_escalations_per_task

    def mark_escalation(self, task: TaskRecord) -> None:
        task.escalation_count += 1

    def _fingerprint(self, text: str) -> str:
        normalized = " ".join(text.lower().split())
        return normalized[:300]
