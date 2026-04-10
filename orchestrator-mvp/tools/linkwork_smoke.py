from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _wrap_windows_command(command: list[str]) -> list[str]:
    if not command:
        return command
    first = str(command[0]).lower()
    if first.endswith(".cmd") or first.endswith(".bat"):
        return ["cmd", "/c", *command]
    return command


def main() -> int:
    command = os.environ.get("ORCH_LINKWORK_COMMAND", "").strip()
    if not command:
        command = str(ROOT.parent / "bin" / "linkwork.cmd")
    job = {
        "executor_id": "linkwork_executor",
        "task_id": "linkwork_smoke_001",
        "task_type": "report_refresh",
        "workspace": str(ROOT),
        "role": "reporter",
        "skill": "evidence_packaging",
        "expected_outputs": ["linkwork-smoke.md"],
        "handoff_contract": {
            "output_boundary": ["generated_files", "evidence_bundle", "summary"],
        },
    }
    completed = subprocess.run(
        _wrap_windows_command([command]),
        input=json.dumps(job, ensure_ascii=False, indent=2),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(ROOT),
        env={**os.environ.copy(), "LINKWORK_TARGET_COMMAND": os.environ.get("LINKWORK_TARGET_COMMAND", "").strip()},
    )
    output = (completed.stdout or completed.stderr or "").strip()
    if not output:
        print("LinkWork smoke produced no output.", file=sys.stderr)
        return 1
    try:
        payload = json.loads(output)
    except Exception as exc:
        print(f"LinkWork smoke output was not JSON: {exc}", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1
    if str(payload.get("status") or "").lower() != "success":
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
