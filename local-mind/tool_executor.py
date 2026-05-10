from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

import yaml

from json_store import read_json, write_json
from local_mind_paths import ROOT
from memory_manager import now_iso


def load_tools() -> dict[str, Any]:
    with (ROOT / "config" / "tools.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["tools"]


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class ToolExecutor:
    def __init__(self) -> None:
        self.tools = load_tools()

    def permission_allows(self, action: dict[str, Any]) -> tuple[bool, str]:
        action_type = action.get("type")
        risk = action.get("risk_level", "low")
        if risk == "high":
            return False, "high-risk action requires manual approval"
        if action_type not in self.tools and action_type != "summarize":
            return False, f"unknown tool: {action_type}"
        if action_type == "summarize":
            return True, "allowed"
        tool = self.tools[action_type]
        if not tool.get("enabled", False):
            return False, f"tool disabled: {action_type}"
        return True, "allowed"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        allowed, reason = self.permission_allows(action)
        if not allowed:
            return {"status": "blocked", "reason": reason}
        action_type = action["type"]
        if action_type == "read_file":
            return self._read_file(action)
        if action_type == "write_file":
            return self._write_file(action)
        if action_type == "run_command":
            return self._run_command(action)
        if action_type == "create_task":
            return self._create_task(action)
        if action_type == "summarize":
            return self._summarize(action)
        return {"status": "blocked", "reason": f"unsupported action type: {action_type}"}

    def _path_allowed(self, action_type: str, target: str) -> tuple[bool, str, Path]:
        tool = self.tools[action_type]
        path = Path(target)
        if not path.is_absolute():
            path = ROOT / target
        for pattern in tool.get("forbidden_patterns", []):
            if fnmatch.fnmatch(path.name, pattern):
                return False, f"forbidden file pattern: {pattern}", path
        for root in tool.get("allowed_roots", []):
            if is_inside(path, Path(root)):
                return True, "allowed", path
        return False, "target outside allowed roots", path

    def _read_file(self, action: dict[str, Any]) -> dict[str, Any]:
        allowed, reason, path = self._path_allowed("read_file", action.get("target", ""))
        if not allowed:
            return {"status": "blocked", "reason": reason, "target": str(path)}
        if not path.exists():
            return {"status": "failed", "reason": "file does not exist", "target": str(path)}
        return {"status": "success", "target": str(path), "content": path.read_text(encoding="utf-8")[:8000]}

    def _write_file(self, action: dict[str, Any]) -> dict[str, Any]:
        allowed, reason, path = self._path_allowed("write_file", action.get("target", ""))
        if not allowed:
            return {"status": "blocked", "reason": reason, "target": str(path)}
        content = action.get("args", {}).get("content", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"status": "success", "target": str(path), "bytes": len(content.encode("utf-8"))}

    def _run_command(self, action: dict[str, Any]) -> dict[str, Any]:
        command = action.get("target", "")
        tool = self.tools["run_command"]
        if any(command.startswith(forbidden) for forbidden in tool.get("forbidden_commands", [])):
            return {"status": "blocked", "reason": "forbidden command", "command": command}
        if not any(command.startswith(allowed) for allowed in tool.get("allowed_commands", [])):
            return {"status": "blocked", "reason": "command not allowlisted", "command": command}
        completed = subprocess.run(
            command,
            cwd=ROOT,
            shell=True,
            capture_output=True,
            text=True,
            timeout=int(tool.get("timeout_seconds", 60)),
        )
        return {
            "status": "success" if completed.returncode == 0 else "failed",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }

    def _create_task(self, action: dict[str, Any]) -> dict[str, Any]:
        path = ROOT / "data" / "task_queue.json"
        queue = read_json(path, {"tasks": []})
        task = {
            "task_id": action.get("args", {}).get("task_id", f"task_{int(Path().stat().st_mtime_ns)}"),
            "title": action.get("target", "Untitled task"),
            "status": "pending",
            "priority": action.get("args", {}).get("priority", 50),
            "risk_level": action.get("risk_level", "low"),
            "created_at": now_iso(),
            "success_criteria": action.get("success_criteria", []),
            "allowed_tools": action.get("args", {}).get("allowed_tools", []),
        }
        queue.setdefault("tasks", []).append(task)
        write_json(path, queue)
        return {"status": "success", "target": str(path), "task_id": task["task_id"]}

    def _summarize(self, action: dict[str, Any]) -> dict[str, Any]:
        target = ROOT / "reports" / "local_mind_status.md"
        state = read_json(ROOT / "data" / "runtime_state.json", {})
        queue = read_json(ROOT / "data" / "task_queue.json", {"tasks": []})
        lines = [
            "# Local Mind Status",
            "",
            f"- Generated at: {now_iso()}",
            f"- Runtime status: {state.get('status')}",
            f"- Last heartbeat: {state.get('last_heartbeat_at')}",
            f"- Task count: {len(queue.get('tasks', []))}",
            "",
            "## Evidence",
            "",
            "- data/runtime_state.json",
            "- data/task_queue.json",
        ]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"status": "success", "target": str(target), "bytes": target.stat().st_size}
