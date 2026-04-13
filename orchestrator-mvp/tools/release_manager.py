from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.release_operations import run_release_operations_status
from tools.release_train_runtime import run_release_train

DATA = ROOT / "data"
OUT = DATA / "release_manager_status.json"
RELEASES = DATA / "release_records.json"
QA_SCRIPT = ROOT / "tools" / "qa_check.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _run_qa() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(QA_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _candidate_summary(releases: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [item for item in releases if item.get("status") in {"prepared", "candidate", "ready"}]
    if not candidates:
        return {"count": 0, "latest": None}
    latest = sorted(
        candidates,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )[0]
    return {
        "count": len(candidates),
        "latest": {
            "id": latest.get("id"),
            "status": latest.get("status"),
            "repo_path": latest.get("repo_path"),
            "branch": latest.get("branch"),
            "artifacts": latest.get("artifacts") or [],
            "blockers": latest.get("blockers") or [],
            "updated_at": latest.get("updated_at") or latest.get("created_at"),
        },
    }


def run_release_manager(*, advance: bool = False) -> dict[str, Any]:
    qa = _run_qa()
    ops = run_release_operations_status()
    releases = _load_json(RELEASES, [])
    blockers: list[str] = []

    readiness = ops.get("operations_readiness", {})
    train = ops.get("release_train", {})

    if not qa["ok"]:
        blockers.append("qa-check-failed")
    if not readiness.get("runtime_ok"):
        blockers.append("runtime-not-ready")
    if not readiness.get("verification_ok"):
        blockers.append("verification-not-ready")
    if not readiness.get("control_ok"):
        blockers.append("control-layer-not-stable")
    if int(train.get("blocked_patch_count", 0)) > 0:
        blockers.append("blocked-patches-present")

    actions: list[str] = []
    if not qa["ok"]:
        actions.append("fix local QA failures before release promotion")
    if not readiness.get("runtime_ok"):
        actions.append("restore runtime heartbeat before advancing release candidates")
    if not readiness.get("control_ok"):
        actions.append("stabilize control layer before release promotion")
    if int(train.get("blocked_patch_count", 0)) > 0:
        actions.append("clear blocked patches before release promotion")
    if not actions:
        actions.append("release gates are green; candidate can be advanced")

    train_payload: dict[str, Any] = {"status": "not-run"}
    if advance and not blockers:
        train_payload = run_release_train(
            runtime_ok=bool(readiness.get("runtime_ok")),
            verification_ok=bool(readiness.get("verification_ok")),
            control_ok=bool(readiness.get("control_ok")),
            blocked_patch_count=int(train.get("blocked_patch_count", 0)),
        )
        releases = _load_json(RELEASES, releases)
    elif advance:
        train_payload = {
            "status": "blocked",
            "reason": "release gates not satisfied",
            "blockers": blockers,
        }

    payload = {
        "updated_at": _utc(),
        "status": "ready" if not blockers else "blocked",
        "advance_requested": advance,
        "qa": qa,
        "release_operations": ops,
        "candidate_summary": _candidate_summary(releases),
        "blockers": blockers,
        "suggested_actions": actions,
        "release_train_result": train_payload,
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    advance = "--advance" in sys.argv[1:]
    print(json.dumps(run_release_manager(advance=advance), ensure_ascii=False, indent=2))
