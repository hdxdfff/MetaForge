from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:8787"
MAX_CONTEXT_FILE_CHARS = 4000


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, timeout: int = 30) -> dict | list:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_text(path: str | None, limit: int | None = None) -> str:
    if not path:
        return ""
    text = Path(path).read_text(encoding="utf-8").strip()
    if limit is not None and len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


def build_prompt(args: argparse.Namespace) -> str:
    base_prompt = args.prompt or ""
    if args.prompt_file:
        base_prompt = read_text(args.prompt_file)

    blocks = [base_prompt.strip()]
    if args.workspace:
        blocks.append(f"Workspace: {args.workspace}")
    if args.current_file:
        blocks.append(f"Current file: {args.current_file}")
    if args.relative_file:
        blocks.append(f"Relative file: {args.relative_file}")
    if args.context_file:
        context_text = read_text(args.context_file, MAX_CONTEXT_FILE_CHARS)
        if context_text:
            blocks.append(f"Attached context from {args.context_file}:\n{context_text}")
    if args.dispatch_hint:
        blocks.append(f"Dispatch hint: {args.dispatch_hint}")
    return "\n\n".join(block for block in blocks if block)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch a task to the local orchestrator unified API")
    parser.add_argument("prompt", nargs="?", help="Task prompt. If omitted, --prompt-file is required.")
    parser.add_argument("--api", default=DEFAULT_API, help="Base URL of the orchestrator API")
    parser.add_argument("--task-file", help="Read a JSON task pack and dispatch each task in order")
    parser.add_argument("--project-id", help="Project memory id")
    parser.add_argument("--repo-path", help="Override repository path")
    parser.add_argument("--goal", help="Optional success goal")
    parser.add_argument("--caller", default="cli", help="Caller label stored with the task")
    parser.add_argument("--context-mode", choices=["lean", "standard", "deep"], help="Optional context mode override")
    parser.add_argument("--max-context-chars", type=int, help="Optional context budget override")
    parser.add_argument("--auto-approve", action="store_true", help="Allow auto-approval for low-risk actions")
    parser.add_argument("--prompt-file", help="Read prompt text from a file")
    parser.add_argument("--workspace", help="Workspace root path for editor handoff")
    parser.add_argument("--current-file", help="Currently focused file path")
    parser.add_argument("--relative-file", help="Relative file path within the workspace")
    parser.add_argument("--context-file", help="Optional file whose content should be attached in a truncated form")
    parser.add_argument("--dispatch-hint", help="Extra routing hint appended to the prompt")
    parser.add_argument("--wait", action="store_true", help="Poll until task reaches a terminal state")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue batch dispatch after a failed task")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds for each API request")
    args = parser.parse_args()

    if args.task_file:
        task_pack = json.loads(Path(args.task_file).read_text(encoding="utf-8"))
        tasks = task_pack.get("tasks") if isinstance(task_pack, dict) else task_pack
        if not isinstance(tasks, list) or not tasks:
            print("Task pack must contain at least one task.", file=sys.stderr)
            return 2
        results: list[dict] = []
        for index, task_payload in enumerate(tasks, start=1):
            if not isinstance(task_payload, dict):
                print(f"Task pack entry {index} is not an object.", file=sys.stderr)
                if not args.continue_on_error:
                    return 2
                continue
            payload = {key: value for key, value in task_payload.items() if value is not None}
            try:
                task = post_json(f"{args.api}/api/dispatch", payload, timeout=args.timeout)
            except urllib.error.URLError as exc:
                print(f"Dispatch failed for pack task {index}: {exc}", file=sys.stderr)
                if not args.continue_on_error:
                    return 1
                continue
            print(json.dumps({
                "pack_index": index,
                "pack_task_id": task_payload.get("task_id"),
                "task_id": task["id"],
                "status": task["status"],
                "repo_path": task.get("repo_path"),
            }, ensure_ascii=False, indent=2))
            results.append(task)
            if args.wait:
                task_id = task["id"]
                terminal = {"completed", "failed"}
                while True:
                    current = get_json(f"{args.api}/api/tasks/{task_id}", timeout=args.timeout)
                    status = current["status"]
                    print(f"task={task_id} status={status}")
                    if status in terminal:
                        print(json.dumps(current.get("result", {}), ensure_ascii=False, indent=2))
                        if status != "completed" and not args.continue_on_error:
                            return 1
                        break
        return 0 if results else 1

    prompt = build_prompt(args).strip()
    if len(prompt) < 8:
        print("Prompt must be at least 8 characters.", file=sys.stderr)
        return 2

    payload = {
        "prompt": prompt,
        "project_id": args.project_id,
        "repo_path": args.repo_path or args.workspace,
        "goal": args.goal,
        "caller": args.caller,
        "auto_approve": args.auto_approve,
        "context_mode": args.context_mode,
        "max_context_chars": args.max_context_chars,
        "allow_resource_scan": True,
        "allow_repo_status": True,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    try:
        task = post_json(f"{args.api}/api/dispatch", payload, timeout=args.timeout)
    except urllib.error.URLError as exc:
        print(f"Dispatch failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "task_id": task["id"],
        "status": task["status"],
        "repo_path": task.get("repo_path"),
    }, ensure_ascii=False, indent=2))

    if not args.wait:
        return 0

    task_id = task["id"]
    terminal = {"completed", "failed"}
    while True:
        current = get_json(f"{args.api}/api/tasks/{task_id}", timeout=args.timeout)
        status = current["status"]
        print(f"status={status}")
        if status in terminal:
            print(json.dumps(current.get("result", {}), ensure_ascii=False, indent=2))
            return 0 if status == "completed" else 1
        import time
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
