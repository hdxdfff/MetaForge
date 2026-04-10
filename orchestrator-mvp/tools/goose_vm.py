#!/usr/bin/env python3
"""Minimal VM-native Goose surface for MetaForge control tasks.

This wrapper gives the tool stack a real Linux-discoverable `goose` command
inside the VM.  It is intentionally conservative: it runs bounded inspection
and audit sequences for ToyOS debt tasks, then emits a structured JSON report.

The wrapper is designed to be a safe first step toward making ToyOS debt
processing self-servable from the VM side without depending on Windows-only
launchers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path("/srv/orchestrator-mvp")
DEFAULT_WORKSPACE = Path("/workspace/generated/toy-os-demo")
GOOSE_CONFIG_DIR = Path("/srv/orchestrator-mvp/.goose")


def _run(command: list[str], *, cwd: Path | None = None, stdin_text: str | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd or ROOT),
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _control_cmd(*args: str, cwd: Path | None = None) -> dict[str, Any]:
    python = ROOT / ".venv" / "bin" / "python"
    command = [str(python), "tools/codex_control.py", *args]
    return _run(command, cwd=cwd or ROOT)


def _collect_audit(workspace: Path, prompt: str) -> dict[str, Any]:
    steps = [
        ("daemon-status", _control_cmd("daemon-status", cwd=ROOT)),
        ("control-layer-status", _control_cmd("control-layer-status", cwd=ROOT)),
        ("engineering-os-status", _control_cmd("engineering-os-status", cwd=ROOT)),
        ("lab-status", _control_cmd("lab-status", cwd=ROOT)),
        ("tool-stack-status", _control_cmd("tool-stack-status", "--refresh", cwd=ROOT)),
        ("tasks", _control_cmd("tasks", "--active-only", "--limit", "20", cwd=ROOT)),
        ("task-route", _control_cmd("task-route", prompt, "--workspace", str(workspace), cwd=ROOT)),
    ]
    return {"steps": steps}


def _collect_build_baseline(workspace: Path, prompt: str) -> dict[str, Any]:
    steps = [
        ("task-route", _control_cmd("task-route", prompt, "--workspace", str(workspace), cwd=ROOT)),
        ("daemon-status", _control_cmd("daemon-status", cwd=ROOT)),
        ("control-layer-status", _control_cmd("control-layer-status", cwd=ROOT)),
        ("engineering-os-status", _control_cmd("engineering-os-status", cwd=ROOT)),
        ("tasks", _control_cmd("tasks", "--active-only", "--limit", "20", cwd=ROOT)),
    ]
    return {"steps": steps}


def _collect_build_break_localization(workspace: Path, prompt: str) -> dict[str, Any]:
    build_log = workspace / "build.log"
    qemu_log = workspace / "build" / "qemu-debug.log"
    snippets: list[dict[str, Any]] = []
    for path in [build_log, qemu_log]:
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # pragma: no cover - best effort only
                snippets.append({"path": str(path), "error": str(exc)})
                continue
            tail = text[-12000:]
            snippets.append({"path": str(path), "tail": tail})
    steps = [
        ("task-route", _control_cmd("task-route", prompt, "--workspace", str(workspace), cwd=ROOT)),
        ("daemon-status", _control_cmd("daemon-status", cwd=ROOT)),
        ("control-layer-status", _control_cmd("control-layer-status", cwd=ROOT)),
        ("build-logs", {"snippets": snippets}),
    ]
    return {"steps": steps}


def _collect_qemu_smoke(workspace: Path, prompt: str) -> dict[str, Any]:
    steps = [
        ("task-route", _control_cmd("task-route", prompt, "--workspace", str(workspace), cwd=ROOT)),
        ("task-delivery-smoke", _control_cmd("task-delivery-smoke", cwd=ROOT)),
        ("execution-kernel-smoke", _control_cmd("execution-kernel-smoke", cwd=ROOT)),
    ]
    return {"steps": steps}


def main() -> int:
    args = sys.argv[1:]
    stdin_text = sys.stdin.read()
    if args and args[0] in {"info", "--info"}:
        GOOSE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        print("version: vm-goose-1")
        print(f"config dir: {GOOSE_CONFIG_DIR}")
        return 0
    if args and args[0] in {"-h", "--help", "help"}:
        print("goose vm-native wrapper")
        print("usage: goose run -i -  # request on stdin")
        print("usage: goose info      # surface availability probe")
        return 0

    request = " ".join(arg for arg in args if arg not in {"run", "-i", "-"}) or stdin_text
    request = request.strip()
    workspace = Path(os.environ.get("GOOSE_WORKSPACE") or DEFAULT_WORKSPACE)
    prompt = request or stdin_text.strip()
    prompt_lower = prompt.lower()

    if not prompt:
        print(json.dumps({
            "status": "empty_request",
            "workspace": str(workspace),
            "hint": "Provide a request on stdin or as arguments.",
        }, indent=2))
        return 0

    if any(token in prompt_lower for token in ["audit", "execution environment", "environment audit"]):
        payload = {
            "status": "completed",
            "task": "audit",
            "request": prompt,
            "workspace": str(workspace),
            "report": _collect_audit(workspace, prompt),
        }
    elif any(token in prompt_lower for token in ["build current runnable baseline", "runnable baseline", "baseline"]):
        payload = {
            "status": "completed",
            "task": "build_baseline",
            "request": prompt,
            "workspace": str(workspace),
            "report": _collect_build_baseline(workspace, prompt),
        }
    elif any(token in prompt_lower for token in ["localize toyos build break", "build break", "failing test", "isolate"]):
        payload = {
            "status": "completed",
            "task": "localize_build_break",
            "request": prompt,
            "workspace": str(workspace),
            "report": _collect_build_break_localization(workspace, prompt),
        }
    elif any(token in prompt_lower for token in ["boot", "qemu", "smoke"]):
        payload = {
            "status": "completed",
            "task": "qemu_smoke_probe",
            "request": prompt,
            "workspace": str(workspace),
            "report": _collect_qemu_smoke(workspace, prompt),
        }
    else:
        payload = {
            "status": "completed",
            "task": "generic_inspection",
            "request": prompt,
            "workspace": str(workspace),
            "report": _collect_audit(workspace, prompt),
        }

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
