from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.static_pipeline import run_pipeline

DATA = ROOT / "data"
SHADOW_ROOT = ROOT / "shadow_factory"
INBOX = SHADOW_ROOT / "inbox"
AUDIT_DIR = SHADOW_ROOT / "audit"
STATUS_PATH = DATA / "shadow_pipeline_bridge_status.json"
TASK_INDEX_PATH = DATA / "shadow_pipeline_tasks_index.json"
TASKS_PATH = DATA / "tasks.json"
_TASK_INDEX_CACHE: dict[str, Any] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _task_source_signature() -> str:
    try:
        stat = TASKS_PATH.stat()
    except FileNotFoundError:
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _iter_task_records() -> list[dict[str, Any]]:
    if not TASKS_PATH.exists():
        return []

    decoder = json.JSONDecoder()

    def refill(handle, buffer: str, pos: int) -> tuple[str, int, bool]:
        chunk = handle.read(65536)
        if not chunk:
            return buffer, pos, False
        if pos:
            buffer = buffer[pos:] + chunk
            pos = 0
        else:
            buffer += chunk
        return buffer, pos, True

    with TASKS_PATH.open("r", encoding="utf-8") as handle:
        buffer = ""
        pos = 0
        eof = False
        while True:
            if pos >= len(buffer):
                buffer, pos, ok = refill(handle, buffer, pos)
                if not ok:
                    return
            while True:
                while pos < len(buffer) and buffer[pos] in " \t\r\n,":
                    pos += 1
                if pos < len(buffer):
                    break
                buffer, pos, ok = refill(handle, buffer, pos)
                if not ok:
                    return
            if buffer[pos] == "[":
                pos += 1
                continue
            if buffer[pos] == "]":
                return
            try:
                record, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                if eof:
                    return
                buffer, pos, ok = refill(handle, buffer, pos)
                eof = not ok
                if not ok:
                    return
                continue
            if isinstance(record, dict):
                yield record
            pos = end
            if pos > 1048576:
                buffer = buffer[pos:]
                pos = 0


def _task_files() -> list[Path]:
    if not INBOX.exists():
        return []
    return sorted((path for path in INBOX.glob("*.json") if path.is_file()), key=lambda path: path.stat().st_mtime)


def pending_shadow_inbox_count() -> int:
    count = 0
    for task_file in _task_files():
        task_packet = _load_json(task_file, {})
        task_id = _task_id(task_packet, task_file)
        if not _already_processed(task_id):
            count += 1
    return count


def pending_shadow_candidate_count() -> int:
    index = _load_task_index()
    count = 0
    for task in index.get("candidates", []):
        if not isinstance(task, dict):
            continue
        packet = _derive_shadow_packet(task)
        if not packet:
            continue
        task_id = str(packet.get("task_id") or "").strip()
        if not task_id:
            continue
        inbox_path = INBOX / f"{task_id}.json"
        if inbox_path.exists() or _already_processed(task_id):
            continue
        count += 1
    return count


def pending_shadow_work_count() -> int:
    return pending_shadow_inbox_count() + pending_shadow_candidate_count()


def _task_id(task_packet: dict[str, Any], task_file: Path) -> str:
    return str(task_packet.get("task_id") or task_file.stem)


def _audit_path(task_id: str) -> Path:
    return AUDIT_DIR / f"audit-{task_id}.json"


def _load_status() -> dict[str, Any]:
    return _load_json(STATUS_PATH, {"updated_at": None, "runs": [], "task_status": {}})


def _record_status(task_id: str, payload: dict[str, Any]) -> None:
    status = _load_status()
    task_status = status.setdefault("task_status", {})
    task_status[task_id] = payload
    runs = status.setdefault("runs", [])
    runs.append({"task_id": task_id, **payload})
    status["updated_at"] = utc_now()
    _write_json(STATUS_PATH, status)


def _already_processed(task_id: str) -> bool:
    status = _load_status()
    task_status = (status.get("task_status") or {}).get(task_id) or {}
    if task_status.get("status") in {"pass", "fail"}:
        return True
    return _audit_path(task_id).exists()


def _is_shadow_candidate(task: dict[str, Any]) -> bool:
    scheduler_hint = task.get("scheduler_hint") or {}
    return any(
        (
            bool(task.get("shadow_mode")),
            str(task.get("execution_mode") or "").strip().lower() == "static_shadow_pipeline",
            str(scheduler_hint.get("execution_mode") or "").strip().lower() == "static_shadow_pipeline",
            str(task.get("task_type") or "").strip().lower() == "shadow_pipeline",
            isinstance(task.get("shadow_task_packet"), dict),
        )
    )


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    scheduler_hint = task.get("scheduler_hint") or {}
    return {
        "task_id": str(task.get("task_id") or task.get("id") or scheduler_hint.get("node_id") or "").strip(),
        "repo_path": str(task.get("repo_path") or task.get("project_path") or "").strip(),
        "goal_id": str(task.get("goal_id") or scheduler_hint.get("goal_id") or "").strip(),
        "title": str(task.get("title") or "").strip(),
        "goal": str(task.get("goal") or "").strip(),
        "execution_mode": str(task.get("execution_mode") or "").strip(),
        "task_type": str(task.get("task_type") or "").strip(),
        "shadow_mode": bool(task.get("shadow_mode")),
        "scheduler_hint": {
            "execution_mode": str(scheduler_hint.get("execution_mode") or "").strip(),
            "goal_id": str(scheduler_hint.get("goal_id") or "").strip(),
            "goal_target": str(scheduler_hint.get("goal_target") or "").strip(),
            "node_id": str(scheduler_hint.get("node_id") or "").strip(),
        },
        "source_task_id": str(task.get("task_id") or task.get("id") or scheduler_hint.get("node_id") or "").strip(),
    }


def _derive_shadow_packet(task: dict[str, Any]) -> dict[str, Any] | None:
    explicit_packet = task.get("shadow_task_packet")
    if isinstance(explicit_packet, dict):
        return explicit_packet
    scheduler_hint = task.get("scheduler_hint") or {}
    task_id = str(task.get("task_id") or scheduler_hint.get("node_id") or "").strip()
    repo_path = str(task.get("repo_path") or task.get("project_path") or "").strip()
    if not task_id or not repo_path:
        return None
    task_slug = task_id.replace(":", "_").replace("/", "_")
    artifact_out_dir = SHADOW_ROOT / "artifacts" / task_slug
    packet: dict[str, Any] = {
        "task_id": task_slug,
        "goal_id": str(scheduler_hint.get("goal_id") or task.get("goal_id") or f"shadow-{task_slug}"),
        "task_type": "build",
        "owner_role": "builder",
        "input_spec": {
            "project_path": repo_path,
            "build_command": "make all",
            "artifact_out_dir": str(artifact_out_dir),
        },
        "expected_outputs": ["build-report.json"],
        "acceptance_checks": ["build report exists"],
        "upstream_task_id": None,
        "artifact_scope": "shadow_only",
        "shadow_mode": True,
        "created_at": utc_now(),
        "source_task_id": task.get("task_id"),
    }
    repo_path_lower = repo_path.lower()
    title_text = " ".join(
        [
            str(task.get("title") or ""),
            str(task.get("goal") or ""),
            str(scheduler_hint.get("goal_target") or ""),
        ]
    ).lower()
    if "toy-os-demo" in repo_path_lower or "toyos" in title_text or "toy-os" in title_text:
        packet["input_spec"]["build_profile"] = "toy_os_build_only"
        packet["expected_outputs"] = ["kernel.bin", "build-report.json"]
        packet["acceptance_checks"] = [
            "build report exists",
            "build success",
            "kernel artifact exists",
        ]
    return packet


def _build_task_index() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for task in _iter_task_records():
        if not _is_shadow_candidate(task):
            continue
        summary = _task_summary(task)
        if not summary.get("task_id") or not summary.get("repo_path"):
            continue
        candidates.append(summary)
    index = {
        "updated_at": utc_now(),
        "source_signature": _task_source_signature(),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    _write_json(TASK_INDEX_PATH, index)
    global _TASK_INDEX_CACHE
    _TASK_INDEX_CACHE = index
    return index


def _load_task_index() -> dict[str, Any]:
    global _TASK_INDEX_CACHE
    signature = _task_source_signature()
    if _TASK_INDEX_CACHE and _TASK_INDEX_CACHE.get("source_signature") == signature:
        return _TASK_INDEX_CACHE
    payload = _load_json(TASK_INDEX_PATH, {})
    if isinstance(payload, dict) and payload.get("source_signature") == signature:
        _TASK_INDEX_CACHE = payload
        return payload
    return _build_task_index()


def _enqueue_shadow_candidates(max_imports: int = 3) -> list[dict[str, Any]]:
    imported: list[dict[str, Any]] = []
    index = _load_task_index()
    for task in index.get("candidates", []):
        if not isinstance(task, dict):
            continue
        packet = _derive_shadow_packet(task)
        if not packet:
            continue
        task_id = str(packet.get("task_id") or "").strip()
        if not task_id:
            continue
        inbox_path = INBOX / f"{task_id}.json"
        if inbox_path.exists() or _already_processed(task_id):
            continue
        _write_json(inbox_path, packet)
        imported.append(
            {
                "task_id": task_id,
                "source_task_id": task.get("task_id"),
                "inbox_path": str(inbox_path),
            }
        )
        if len(imported) >= max_imports:
            break
    return imported


def run_shadow_pipeline_bridge(*, max_tasks: int = 1) -> dict[str, Any]:
    imported = _enqueue_shadow_candidates(max_imports=max_tasks)
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    pending_files = _task_files()
    for task_file in pending_files:
        task_packet = _load_json(task_file, {})
        task_id = _task_id(task_packet, task_file)
        if _already_processed(task_id):
            skipped.append({"task_id": task_id, "task_file": str(task_file), "reason": "already-processed"})
            continue
        try:
            result = run_pipeline(task_packet)
            record = {
                "status": str(result.get("verdict") or "unknown"),
                "task_file": str(task_file),
                "audit_path": str(_audit_path(task_id)),
                "updated_at": utc_now(),
            }
            _record_status(task_id, record)
            processed.append(
                {
                    "task_id": task_id,
                    "task_file": str(task_file),
                    "verdict": result.get("verdict"),
                    "audit_id": result.get("audit_id"),
                }
            )
        except Exception as exc:
            record = {
                "status": "error",
                "task_file": str(task_file),
                "error": f"{type(exc).__name__}: {exc}",
                "updated_at": utc_now(),
            }
            _record_status(task_id, record)
            processed.append(
                {
                    "task_id": task_id,
                    "task_file": str(task_file),
                    "verdict": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if len(processed) >= max_tasks:
            break
    return {
        "updated_at": utc_now(),
        "status": "idle" if not processed else "processed",
        "imported_count": len(imported),
        "imported": imported,
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "pending_count": max(0, len(pending_files) - len(processed) - len(skipped)),
        "processed": processed,
        "skipped": skipped[:10],
        "status_path": str(STATUS_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run shadow pipeline bridge for inbox tasks")
    parser.add_argument("--max-tasks", type=int, default=1)
    args = parser.parse_args()
    result = run_shadow_pipeline_bridge(max_tasks=max(1, args.max_tasks))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
