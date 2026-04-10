from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
DATA = ROOT / "data"
DAEMON = DATA / "factory_daemon_state.json"
REALITY = DATA / "reality_dashboard.json"
TASKS = DATA / "tasks.json"
TASK_HISTORY = DATA / "task_history.json"
FACTORY_LOG = DATA / "factory_daemon.log"
VERIFICATION_STATUS = DATA / "verification_status.json"
ARTIFACT_REGISTRY = DATA / "artifact_registry.json"
PRIORITY_DIRECTIVES = DATA / "priority_directives.json"
MEMORY_KERNEL = DATA / "memory_kernel.json"
CONTEXT_CACHE = DATA / "context_cache.json"
CONTEXT_KERNEL = DATA / "context_kernel.json"
HOT_CONTEXT = DATA / "hot_context.json"
DIALOGUE_MEMORY = DATA / "dialogue_memory.json"
SELF_MODEL_RUNTIME = DATA / "self_model_runtime.json"
SOAK_STATE = DATA / "soak_monitor_state.json"

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def _windows_process_handle(pid: int):
    handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    return handle


def _windows_process_snapshot(pid: int) -> dict[str, Any] | None:
    handle = _windows_process_handle(pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        image_path = None
        if _KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            image_path = buffer.value
        return {
            "Id": int(pid),
            "ProcessName": Path(image_path).name if image_path else f"pid_{pid}",
            "ImagePath": image_path,
        }
    finally:
        _KERNEL32.CloseHandle(handle)
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc

TERMINAL_STATUSES = {"completed", "failed", "timed_out", "cancelled", "skipped"}
ACTIVE_STATUSES = {"planning", "queued", "running"}
CONTEXT_FILES = [
    CONTEXT_CACHE,
    CONTEXT_KERNEL,
    HOT_CONTEXT,
    DIALOGUE_MEMORY,
    SELF_MODEL_RUNTIME,
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    value = value or utc_now()
    return value.isoformat().replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_log_stamp(line: str) -> datetime | None:
    if not line.startswith("[") or "]" not in line:
        return None
    stamp = line[1 : line.index("]")]
    try:
        local_value = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
        return local_value.astimezone(timezone.utc)
    except Exception:
        return None


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def file_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def tail_lines(path: Path, limit: int = 200) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []


def count_statuses(items: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in items:
        status = str(item.get("status") or "").strip().lower() or "unknown"
        counter[status] += 1
    return dict(counter)


def recent_recovery_tasks(tasks: list[dict[str, Any]], start_at: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in tasks:
        text = " ".join(str(item.get(key) or "") for key in ("title", "goal", "prompt"))
        if "recovery" not in text.lower():
            continue
        updated_at = parse_utc(item.get("updated_at"))
        if updated_at and updated_at >= start_at:
            rows.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "title": item.get("title"),
                    "goal": item.get("goal"),
                    "updated_at": item.get("updated_at"),
                }
            )
    return rows


def history_tail_counts(history: list[dict[str, Any]], tail: int = 200) -> dict[str, int]:
    return count_statuses(history[-tail:])


def task_snapshot(tasks: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = count_statuses(tasks)
    active_count = sum(status_counts.get(status, 0) for status in ACTIVE_STATUSES)
    terminal_counts = {status: status_counts.get(status, 0) for status in TERMINAL_STATUSES}
    history_counts = history_tail_counts(history, tail=200)
    return {
        "tasks_status_counts": status_counts,
        "active_task_count": active_count,
        "terminal_counts": terminal_counts,
        "history_status_counts_tail200": history_counts,
        "history_len": len(history),
        "tasks_len": len(tasks),
    }


def context_snapshot() -> dict[str, int]:
    return {
        "memory_kernel_bytes": file_size(MEMORY_KERNEL),
        "context_cache_bytes": file_size(CONTEXT_CACHE),
        "context_kernel_bytes": file_size(CONTEXT_KERNEL),
        "hot_context_bytes": file_size(HOT_CONTEXT),
        "dialogue_memory_bytes": file_size(DIALOGUE_MEMORY),
        "self_model_runtime_bytes": file_size(SELF_MODEL_RUNTIME),
        "total_context_bytes": sum(file_size(path) for path in CONTEXT_FILES),
    }


def process_snapshot(pid: int | None) -> dict[str, Any] | None:
    if not pid:
        return None
    try:
        if sys.platform == "win32":
            return _windows_process_snapshot(pid)
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,comm="],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or "").strip()
    if not output:
        return None
    parts = output.split(maxsplit=1)
    return {
        "Id": pid,
        "ProcessName": parts[1] if len(parts) > 1 else f"pid_{pid}",
        "ImagePath": None,
    }


def focus_artifact_config(focus_artifact_id: str | None) -> dict[str, Any] | None:
    artifact_id = str(focus_artifact_id or "").strip().lower()
    if not artifact_id:
        directive = load_json(PRIORITY_DIRECTIVES, {}) or {}
        artifact_id = str(((directive.get("soak_focus") or {}).get("artifact_id")) or "").strip().lower()
    if artifact_id != "toy-os-demo":
        return None
    base = ROOT.parent / "generated" / "toy-os-demo"
    required = [
        base / "build-report.json",
        base / "build" / "build.log",
        base / "build" / "kernel.bin",
        base / "build" / "generic-qemu-smoke-report.json",
        base / "build" / "artifact.sha256",
        base / "artifact_manifest.json",
    ]
    return {
        "artifact_id": "toy-os-demo",
        "artifact_path": str(base),
        "required_artifacts": [str(path) for path in required],
    }


def focus_artifact_snapshot(focus: dict[str, Any] | None, *, start_at: datetime | None = None) -> dict[str, Any] | None:
    if not focus:
        return None
    required_paths = [Path(path) for path in focus.get("required_artifacts") or []]
    build_report_path = next((path for path in required_paths if path.name == "build-report.json"), None)
    qemu_report_path = next((path for path in required_paths if path.name == "generic-qemu-smoke-report.json"), None)
    manifest_path = next((path for path in required_paths if path.name == "artifact_manifest.json"), None)
    build_report = load_json(build_report_path, {}) if build_report_path else {}
    qemu_report = load_json(qemu_report_path, {}) if qemu_report_path else {}
    manifest = load_json(manifest_path, {}) if manifest_path else {}
    verification = load_json(VERIFICATION_STATUS, {}) or {}
    artifact_registry = load_json(ARTIFACT_REGISTRY, {}) or {}
    artifact_registry_status = str(artifact_registry.get("status") or "").strip().lower()
    artifact_registry_issues = artifact_registry.get("issues") or []
    log_tail = tail_lines(FACTORY_LOG, limit=200)
    recent_tail = [
        line for line in log_tail if start_at is None or ((parse_log_stamp(line) or datetime.min.replace(tzinfo=timezone.utc)) >= start_at)
    ]
    permission_errors = [line for line in recent_tail if "PermissionError" in line]
    provider_errors = [
        line
        for line in recent_tail
        if "provider" in line.lower() and ("error" in line.lower() or "failed" in line.lower())
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    return {
        "artifact_id": focus.get("artifact_id"),
        "artifact_path": focus.get("artifact_path"),
        "required_total": len(required_paths),
        "required_present": len(required_paths) - len(missing),
        "missing_required_artifacts": missing,
        "build_success": bool(build_report.get("build_success")),
        "build_ready": bool(build_report.get("build_ready")),
        "qemu_status": qemu_report.get("status"),
        "manifest_reproducible": bool(manifest.get("reproducible")),
        "verification_status": verification.get("status"),
        "verification_pending_checks": ((verification.get("delayed_verification") or {}).get("pending_checks") or []),
        "artifact_audit_passed": artifact_registry_status == "pass" and len(artifact_registry_issues) == 0,
        "artifact_issue_count": len(artifact_registry_issues),
        "permission_error_count_tail200": len(permission_errors),
        "provider_error_count_tail200": len(provider_errors),
    }


def collect_sample(start_at: datetime, *, focus_artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    daemon = load_json(DAEMON, {})
    reality = load_json(REALITY, {})
    tasks = load_json(TASKS, [])
    history = load_json(TASK_HISTORY, [])
    last_result = daemon.get("last_result") or {}
    guard = last_result.get("guard") or {}
    economics = last_result.get("economics_engine") or {}
    task_market = economics.get("task_market") or {}
    execution_recovery = last_result.get("execution_recovery") or {}
    pid = daemon.get("pid")

    snapshot = task_snapshot(tasks, history)
    context = context_snapshot()
    recovery_rows = recent_recovery_tasks(tasks, start_at)
    focus_snapshot = focus_artifact_snapshot(focus_artifact, start_at=start_at)

    return {
        "at": utc_text(),
        "pid": pid,
        "status": daemon.get("status"),
        "cycle": daemon.get("cycle"),
        "last_tick_at": daemon.get("last_tick_at"),
        "heartbeat_at": daemon.get("heartbeat_at"),
        "ai_testing_alert": daemon.get("ai_testing_alert"),
        "last_error": daemon.get("last_error"),
        "tasks_status_counts": snapshot["tasks_status_counts"],
        "active_task_count": snapshot["active_task_count"],
        "task_history_status_counts_tail200": snapshot["history_status_counts_tail200"],
        "history_len": snapshot["history_len"],
        "tasks_len": snapshot["tasks_len"],
        "open_tasks_market": task_market.get("open_task_count"),
        "completed_tasks_market": task_market.get("completed_task_count"),
        "failed_tasks_market": task_market.get("failed_task_count"),
        "active_tasks_guard": (guard.get("tasks") or {}).get("active"),
        "products_real": reality.get("products_real"),
        "artifacts_produced_last_24h": reality.get("artifacts_produced_last_24h"),
        "technical_artifacts_produced_last_24h": reality.get("technical_artifacts_produced_last_24h"),
        "recent_real_artifact_ids": reality.get("recent_real_artifact_ids") or [],
        "unverified_completed_tasks_last_24h": (reality.get("data_quality") or {}).get("unverified_completed_tasks_last_24h"),
        "execution_recovery": {
            "status": execution_recovery.get("status"),
            "recovery_mode": execution_recovery.get("recovery_mode"),
            "active_recovery_task_ids": execution_recovery.get("active_recovery_task_ids") or [],
            "fresh_completed_tasks": execution_recovery.get("fresh_completed_tasks"),
            "fresh_real_artifacts": execution_recovery.get("fresh_real_artifacts"),
            "active_non_recovery_tasks": execution_recovery.get("active_non_recovery_tasks"),
            "needs_fresh_completion": execution_recovery.get("needs_fresh_completion"),
            "needs_artifact_recovery": execution_recovery.get("needs_artifact_recovery"),
            "recent_recovery_tasks": recovery_rows[-10:],
            "recent_recovery_task_count": len(recovery_rows),
        },
        "focus_artifact": focus_snapshot,
        "context": context,
        "process": process_snapshot(pid),
    }


def compute_summary(start_sample: dict[str, Any], samples: list[dict[str, Any]], duration_seconds: int, sample_seconds: int) -> dict[str, Any]:
    series = [start_sample, *samples]
    pids = [sample.get("pid") for sample in series if sample.get("pid")]
    cycles = [int(sample.get("cycle") or 0) for sample in series]
    active_counts = [int(sample.get("active_task_count") or 0) for sample in series]
    artifacts24 = [int(sample.get("artifacts_produced_last_24h") or 0) for sample in series]
    unverified = [int(sample.get("unverified_completed_tasks_last_24h") or 0) for sample in series]
    recovery_counts = [int(((sample.get("execution_recovery") or {}).get("recent_recovery_task_count") or 0)) for sample in series]
    recovery_modes = [bool((sample.get("execution_recovery") or {}).get("recovery_mode")) for sample in series]
    active_recovery = [len((sample.get("execution_recovery") or {}).get("active_recovery_task_ids") or []) for sample in series]
    context_bytes = [int(((sample.get("context") or {}).get("total_context_bytes") or 0)) for sample in series]
    memory_ws = [int(((sample.get("process") or {}).get("WorkingSet64") or 0)) for sample in series]
    private_mem = [int(((sample.get("process") or {}).get("PrivateMemorySize64") or 0)) for sample in series]
    focus_series = [sample.get("focus_artifact") or {} for sample in series]
    focus_required_totals = [int(item.get("required_total") or 0) for item in focus_series]
    focus_required_present = [int(item.get("required_present") or 0) for item in focus_series]
    focus_permission_errors = [int(item.get("permission_error_count_tail200") or 0) for item in focus_series]
    focus_provider_errors = [int(item.get("provider_error_count_tail200") or 0) for item in focus_series]
    focus_verification_pending = [len(item.get("verification_pending_checks") or []) for item in focus_series]
    focus_artifact_audit = [bool(item.get("artifact_audit_passed")) for item in focus_series]

    cycle_non_decreasing = all(current >= previous for previous, current in zip(cycles, cycles[1:]))
    pid_changes = sum(current != previous for previous, current in zip(pids, pids[1:]))
    timed_out_start = int((start_sample.get("tasks_status_counts") or {}).get("timed_out", 0))
    timed_out_end = int((samples[-1].get("tasks_status_counts") or {}).get("timed_out", timed_out_start)) if samples else timed_out_start
    completed_start = int((start_sample.get("tasks_status_counts") or {}).get("completed", 0))
    completed_end = int((samples[-1].get("tasks_status_counts") or {}).get("completed", completed_start)) if samples else completed_start
    failed_start = int((start_sample.get("tasks_status_counts") or {}).get("failed", 0))
    failed_end = int((samples[-1].get("tasks_status_counts") or {}).get("failed", failed_start)) if samples else failed_start

    timed_out_delta = timed_out_end - timed_out_start
    completed_delta = completed_end - completed_start
    failed_delta = failed_end - failed_start
    artifact_drop_to_zero = any(value <= 0 for value in artifacts24)

    memory_growth = {
        "working_set_delta_bytes": (memory_ws[-1] - memory_ws[0]) if memory_ws else 0,
        "working_set_peak_bytes": max(memory_ws) if memory_ws else 0,
        "private_delta_bytes": (private_mem[-1] - private_mem[0]) if private_mem else 0,
        "private_peak_bytes": max(private_mem) if private_mem else 0,
        "context_delta_bytes": (context_bytes[-1] - context_bytes[0]) if context_bytes else 0,
        "context_peak_bytes": max(context_bytes) if context_bytes else 0,
    }
    memory_growth_reasonable = (
        abs(memory_growth["working_set_delta_bytes"]) <= max(512 * 1024 * 1024, int(memory_ws[0] * 0.5) if memory_ws else 0)
        and memory_growth["context_delta_bytes"] <= max(25 * 1024 * 1024, int(context_bytes[0] * 0.5) if context_bytes else 0)
    )

    checks = {
        "pid_stable": pid_changes == 0,
        "cycle_advancing": (cycles[-1] - cycles[0]) >= max(1, len(samples) // 3) if cycles else False,
        "tasks_not_piling_up": (max(active_counts) if active_counts else 0) <= max(6, (active_counts[0] if active_counts else 0) + 3),
        "tasks_not_all_timed_out": not (timed_out_delta > 0 and completed_delta <= 0 and failed_delta <= 0),
        "artifacts_still_present": not artifact_drop_to_zero and (artifacts24[-1] > 0 if artifacts24 else False),
        "memory_context_not_bloated": memory_growth_reasonable,
        "recovery_not_looping": not ((max(recovery_counts) if recovery_counts else 0) >= 3 or (max(active_recovery) if active_recovery else 0) >= 2),
    }
    focus_enabled = any(total > 0 for total in focus_required_totals)
    focus_checks = {}
    if focus_enabled:
        focus_checks = {
            "required_artifacts_present": all(present >= total for present, total in zip(focus_required_present, focus_required_totals)),
            "no_permission_errors": max(focus_permission_errors) == 0,
            "no_provider_errors": max(focus_provider_errors) == 0,
            "verification_stays_pass": max(focus_verification_pending) == 0,
            "artifact_audit_stays_pass": all(focus_artifact_audit),
        }
        checks.update({f"focus_{name}": value for name, value in focus_checks.items()})
    return {
        "planned_duration_seconds": duration_seconds,
        "sample_seconds": sample_seconds,
        "sample_count": len(samples),
        "pid_changes": pid_changes,
        "unique_pids": sorted({pid for pid in pids if pid}),
        "cycle_start": cycles[0] if cycles else 0,
        "cycle_end": cycles[-1] if cycles else 0,
        "cycle_delta": (cycles[-1] - cycles[0]) if cycles else 0,
        "cycle_monotonic_non_decreasing": cycle_non_decreasing,
        "max_active_task_count": max(active_counts) if active_counts else 0,
        "end_active_task_count": active_counts[-1] if active_counts else 0,
        "timed_out_delta": timed_out_delta,
        "completed_delta": completed_delta,
        "failed_delta": failed_delta,
        "artifact_drop_to_zero": artifact_drop_to_zero,
        "artifact_count_min": min(artifacts24) if artifacts24 else 0,
        "artifact_count_max": max(artifacts24) if artifacts24 else 0,
        "unverified_completed_peak": max(unverified) if unverified else 0,
        "recovery_trigger_count": max(recovery_counts) if recovery_counts else 0,
        "recovery_mode_samples": sum(1 for item in recovery_modes if item),
        "recovery_active_peak": max(active_recovery) if active_recovery else 0,
        "recovery_loop_detected": (max(recovery_counts) if recovery_counts else 0) >= 3 or (max(active_recovery) if active_recovery else 0) >= 2,
        "focus_artifact": {
            "enabled": focus_enabled,
            "artifact_id": (focus_series[-1] or {}).get("artifact_id") if focus_series else None,
            "required_present_min": min(focus_required_present) if focus_required_present else 0,
            "required_total_max": max(focus_required_totals) if focus_required_totals else 0,
            "permission_error_count_peak": max(focus_permission_errors) if focus_permission_errors else 0,
            "provider_error_count_peak": max(focus_provider_errors) if focus_provider_errors else 0,
            "verification_pending_peak": max(focus_verification_pending) if focus_verification_pending else 0,
            "artifact_audit_always_pass": all(focus_artifact_audit) if focus_artifact_audit else False,
            "checks": focus_checks,
        },
        "memory_growth": memory_growth,
        "memory_growth_reasonable": memory_growth_reasonable,
        "checks": checks,
        "passed": all(checks.values()),
    }


def write_state(payload: dict[str, Any]) -> None:
    atomic_write_json(SOAK_STATE, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample daemon stability over time.")
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--sample-seconds", type=int, default=60)
    parser.add_argument("--label", default="")
    parser.add_argument("--focus-artifact", default="")
    args = parser.parse_args()

    started_at = utc_now()
    stamp = started_at.strftime("%Y%m%dT%H%M%S")
    report_path = DATA / f"soak_report_{stamp}.json"
    focus_artifact = focus_artifact_config(args.focus_artifact)
    start_sample = collect_sample(started_at, focus_artifact=focus_artifact)
    tasks = load_json(TASKS, [])
    history = load_json(TASK_HISTORY, [])
    start_task_snapshot = task_snapshot(tasks, history)

    state = {
        "status": "running",
        "started_at": utc_text(started_at),
        "sample_seconds": args.sample_seconds,
        "planned_minutes": round(args.duration_seconds / 60),
        "label": args.label,
        "focus_artifact": focus_artifact,
        "report_path": str(report_path),
        "start_task_snapshot": start_task_snapshot,
        "start_sample": start_sample,
        "samples": [],
    }
    write_state(state)

    deadline = time.monotonic() + args.duration_seconds
    minute = 0
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        time.sleep(min(args.sample_seconds, max(0.0, remaining)))
        if time.monotonic() > deadline + 1:
            break
        minute += max(1, round(args.sample_seconds / 60))
        sample = collect_sample(started_at, focus_artifact=focus_artifact)
        sample["minute"] = minute
        samples.append(sample)
        state["samples"] = samples
        state["last_sample"] = sample
        state["samples_collected"] = len(samples)
        state["last_updated_at"] = utc_text()
        write_state(state)
        print(
            json.dumps(
                {
                    "minute": minute,
                    "pid": sample.get("pid"),
                    "cycle": sample.get("cycle"),
                    "active_tasks": sample.get("active_task_count"),
                    "artifacts24h": sample.get("artifacts_produced_last_24h"),
                    "recovery_mode": (sample.get("execution_recovery") or {}).get("recovery_mode"),
                    "recovery_recent_count": (sample.get("execution_recovery") or {}).get("recent_recovery_task_count"),
                    "focus_required_present": ((sample.get("focus_artifact") or {}).get("required_present")),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = compute_summary(start_sample, samples, args.duration_seconds, args.sample_seconds)
    report = {
        "started_at": utc_text(started_at),
        "finished_at": utc_text(),
        "sample_seconds": args.sample_seconds,
        "planned_minutes": round(args.duration_seconds / 60),
        "label": args.label,
        "focus_artifact": focus_artifact,
        "start_task_snapshot": start_task_snapshot,
        "start_sample": start_sample,
        "samples": samples,
        "summary": summary,
    }
    atomic_write_json(report_path, report)
    write_state(
        {
            "status": "completed",
            "started_at": utc_text(started_at),
            "finished_at": utc_text(),
            "sample_seconds": args.sample_seconds,
            "planned_minutes": round(args.duration_seconds / 60),
            "label": args.label,
            "report_path": str(report_path),
            "summary": summary,
            "samples_collected": len(samples),
            "last_sample": samples[-1] if samples else start_sample,
        }
    )
    print(json.dumps({"report_path": str(report_path), "passed": summary["passed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
