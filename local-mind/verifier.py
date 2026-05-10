from __future__ import annotations

from pathlib import Path
from typing import Any


class Verifier:
    def verify(self, action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if result.get("status") != "success":
            return {"verified": False, "notes": result.get("reason", "action did not succeed")}
        action_type = action.get("type")
        if action_type in {"write_file", "summarize"}:
            path = Path(result.get("target", ""))
            if not path.exists():
                return {"verified": False, "notes": "target file does not exist"}
            if path.stat().st_size <= 0:
                return {"verified": False, "notes": "target file is empty"}
            return {"verified": True, "notes": f"file exists and is non-empty: {path}"}
        if action_type == "read_file":
            return {"verified": bool(result.get("content") is not None), "notes": "read produced content field"}
        if action_type == "run_command":
            return {"verified": result.get("returncode") == 0, "notes": f"returncode={result.get('returncode')}"}
        if action_type == "create_task":
            return {"verified": bool(result.get("task_id")), "notes": "task id was returned"}
        return {"verified": True, "notes": "success result accepted for low-risk action"}

    def all_success_criteria_met(self, task: dict[str, Any], results: list[dict[str, Any]]) -> bool:
        if not results:
            return False
        return all(item.get("verified", {}).get("verified") for item in results)
