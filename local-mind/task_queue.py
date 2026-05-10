from __future__ import annotations

from typing import Any

from json_store import read_json, write_json
from local_mind_paths import ROOT
from memory_manager import now_iso


QUEUE_PATH = ROOT / "data" / "task_queue.json"


class TaskQueue:
    def read(self) -> dict[str, Any]:
        return read_json(QUEUE_PATH, {"tasks": []})

    def write(self, queue: dict[str, Any]) -> None:
        write_json(QUEUE_PATH, queue)

    def pending(self) -> list[dict[str, Any]]:
        tasks = self.read().get("tasks", [])
        return [task for task in tasks if task.get("status") == "pending"]

    def select_next(self) -> dict[str, Any] | None:
        pending = self.pending()
        if not pending:
            return None
        return sorted(pending, key=lambda task: task.get("priority", 0), reverse=True)[0]

    def update_status(self, task_id: str, status: str, evidence: str | None = None, notes: str | None = None) -> None:
        queue = self.read()
        for task in queue.get("tasks", []):
            if task.get("task_id") == task_id:
                task["status"] = status
                task["updated_at"] = now_iso()
                if evidence:
                    task["evidence"] = evidence
                if notes:
                    task["notes"] = notes
                break
        self.write(queue)
