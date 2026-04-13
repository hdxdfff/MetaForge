from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_REPORT = DATA / "ai_test_report.json"
LEGACY_STATUS = DATA / "ai_test_status.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _fallback_status(report_path: str | Path | None = None, *, error: Exception | None = None) -> dict[str, Any]:
    candidates = []
    if report_path:
        candidates.append(Path(report_path))
    candidates.extend([DEFAULT_REPORT, LEGACY_STATUS])

    payload: dict[str, Any] = {}
    for candidate in candidates:
        payload = _load_json(candidate)
        if payload:
            break

    if not payload:
        payload = {
            "status": "missing",
            "pass_rate": 0.0,
            "error_count": 0,
            "failing_case_ids": [],
            "all_passed": False,
            "all_release_blockers_passed": False,
            "failed_release_blocker_case_ids": [],
        }

    payload.setdefault("status", "missing")
    payload.setdefault("pass_rate", 0.0)
    payload.setdefault("error_count", 0)
    payload.setdefault("failing_case_ids", [])
    payload.setdefault("all_passed", False)
    payload.setdefault("all_release_blockers_passed", False)
    payload.setdefault("failed_release_blocker_case_ids", [])
    payload["compat_fallback"] = True
    if error is not None:
        payload["compat_error"] = f"{error.__class__.__name__}: {error}"
    return payload


def load_ai_test_status(report_path: str | Path | None = None) -> dict[str, Any]:
    try:
        module = importlib.import_module("tools.ai_test_automation")
        func = getattr(module, "load_ai_test_status")
        if report_path is None:
            return func()
        return func(report_path)
    except Exception as error:
        return _fallback_status(report_path, error=error)


def run_ai_test_suite(*args, **kwargs) -> dict[str, Any]:
    try:
        module = importlib.import_module("tools.ai_test_automation")
        func = getattr(module, "run_ai_test_suite")
        return func(*args, **kwargs)
    except Exception as error:
        payload = _fallback_status(kwargs.get("report_path"), error=error)
        payload["status"] = "disabled"
        payload["run_skipped"] = True
        payload["reason"] = "ai_test_automation unavailable"
        return payload
