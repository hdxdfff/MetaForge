from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VERIFICATION_STATUS = DATA / "verification_status.json"
RELEASE_OPERATIONS_STATUS = DATA / "release_operations_status.json"
CONTROL_LAYER_STATUS = DATA / "control_layer_status.json"
STATUS_PATH = DATA / "fact_gate_convergence_status.json"
HISTORY_PATH = DATA / "fact_gate_convergence_history.json"
HISTORY_LIMIT = 60
CONVERGENCE_STREAK_TARGET = 3
CONVERGENCE_WINDOW_TARGET = 5
CONVERGENCE_WINDOW_SIZE = 12


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _source_snapshot(path: Path) -> dict[str, Any]:
    payload = _load_json(path, {})
    updated_at = payload.get("updated_at")
    parsed = _parse_timestamp(updated_at)
    age_seconds = None
    if parsed is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    return {
        "path": str(path),
        "updated_at": updated_at,
        "age_seconds": age_seconds,
        "stale": bool(payload.get("stale")),
        "source": payload.get("source"),
        "status": payload.get("status"),
    }


def _gate_from_verification() -> dict[str, Any]:
    verification = _load_json(VERIFICATION_STATUS, {})
    fact_consistency = verification.get("fact_consistency") or {}
    release_gate = verification.get("release_gate") or {}
    passed = bool(fact_consistency.get("passed"))
    contradictions = [str(item) for item in (fact_consistency.get("contradictions") or []) if str(item).strip()]
    if release_gate.get("status") not in {"pass", "ready"}:
        passed = False
    if release_gate.get("blocking_sample_failures"):
        passed = False
    blocking_reasons: list[str] = []
    if contradictions:
        blocking_reasons.append("fact_consistency_contradictions")
    if release_gate.get("blocking_sample_failures"):
        blocking_reasons.append("verification_release_blockers")
    return {
        "passed": passed,
        "status": "pass" if passed else "attention",
        "fact_consistency": {
            "passed": bool(fact_consistency.get("passed")),
            "contradictions": contradictions,
        },
        "verification_gate": {
            "passed": release_gate.get("status") in {"pass", "ready"},
            "status": release_gate.get("status"),
            "blocking_sample_failures": list(release_gate.get("blocking_sample_failures") or [])[:10],
            "sample_failures": list(release_gate.get("sample_failures") or [])[:10],
        },
        "blocking_reasons": blocking_reasons,
    }


def _gate_from_release() -> dict[str, Any]:
    release_ops = _load_json(RELEASE_OPERATIONS_STATUS, {})
    release_claim_policy = release_ops.get("release_claim_policy") or {}
    release_tiers = release_ops.get("release_tiers") or {}
    delivery_ready = release_ops.get("delivery_ready_state_machine") or {}
    delivery_ready_count = int((delivery_ready.get("counts") or {}).get("delivery_ready") or 0)
    mainline_ready = str((release_tiers.get("mainline") or {}).get("status") or "").strip().lower() == "ready"
    delivery_gate_ok = bool(delivery_ready_count > 0 and mainline_ready and not release_claim_policy.get("blocks_release"))
    blocking_reasons: list[str] = []
    if release_claim_policy.get("blocks_release"):
        blocking_reasons.extend(str(item) for item in (release_claim_policy.get("blocking_reasons") or []) if str(item).strip())
    if delivery_ready_count <= 0:
        blocking_reasons.append("delivery-ready-count-zero")
    if not mainline_ready:
        blocking_reasons.append("mainline-release-tier-not-ready")
    return {
        "passed": delivery_gate_ok,
        "status": "pass" if delivery_gate_ok else "attention",
        "delivery_gate_ok": delivery_gate_ok,
        "delivery_ready_count": delivery_ready_count,
        "release_claim_policy": {
            "passed": bool(release_claim_policy.get("passed")),
            "blocks_release": bool(release_claim_policy.get("blocks_release")),
            "status": release_claim_policy.get("status"),
        },
        "release_tiers": {
            "mainline": {
                "status": (release_tiers.get("mainline") or {}).get("status"),
            }
        },
        "blocking_reasons": blocking_reasons,
    }


def _load_history() -> dict[str, Any]:
    return _load_json(HISTORY_PATH, {"version": 1, "samples": []})


def _write_history(samples: list[dict[str, Any]]) -> None:
    atomic_write_json(HISTORY_PATH, {"version": 1, "updated_at": _utc(), "samples": samples[-HISTORY_LIMIT:]})


def _score_window(samples: list[dict[str, Any]]) -> dict[str, Any]:
    window = samples[-CONVERGENCE_WINDOW_SIZE:]
    window_pass_count = sum(1 for item in window if bool(item.get("all_passed")))
    consecutive_pass_count = 0
    for item in reversed(samples):
        if bool(item.get("all_passed")):
            consecutive_pass_count += 1
        else:
            break
    converged = bool(
        consecutive_pass_count >= CONVERGENCE_STREAK_TARGET
        and window_pass_count >= CONVERGENCE_WINDOW_TARGET
        and window
        and all(bool(item.get("all_passed")) for item in window[-CONVERGENCE_STREAK_TARGET:])
    )
    return {
        "window_size": len(window),
        "window_pass_count": window_pass_count,
        "window_pass_rate": round(window_pass_count / len(window), 4) if window else 0.0,
        "consecutive_pass_count": consecutive_pass_count,
        "converged": converged,
    }


def run_fact_gate_convergence(*, write_outputs: bool = True) -> dict[str, Any]:
    verification_gate = _gate_from_verification()
    delivery_gate = _gate_from_release()
    all_passed = bool(verification_gate["passed"] and delivery_gate["passed"])
    guard = {
        "updated_at": _utc(),
        "status": "pass" if all_passed else "attention",
        "all_passed": all_passed,
        "current": {
            "fact_consistency": verification_gate["fact_consistency"],
            "verification_gate": verification_gate["verification_gate"],
            "delivery_gate": {
                "passed": delivery_gate["passed"],
                "status": delivery_gate["status"],
                "delivery_gate_ok": delivery_gate["delivery_gate_ok"],
                "delivery_ready_count": delivery_gate["delivery_ready_count"],
            },
        },
        "sources": {
            "verification_status": _source_snapshot(VERIFICATION_STATUS),
            "release_operations_status": _source_snapshot(RELEASE_OPERATIONS_STATUS),
            "control_layer_status": _source_snapshot(CONTROL_LAYER_STATUS),
        },
        "blocking_reasons": [
            *verification_gate.get("blocking_reasons", []),
            *delivery_gate.get("blocking_reasons", []),
        ],
    }

    history_payload = _load_history()
    samples = list(history_payload.get("samples") or [])
    samples.append(
        {
            "updated_at": guard["updated_at"],
            "all_passed": all_passed,
            "fact_consistency_pass": bool(verification_gate["fact_consistency"]["passed"]),
            "verification_gate_pass": bool(verification_gate["verification_gate"]["passed"]),
            "delivery_gate_pass": bool(delivery_gate["passed"]),
            "blocking_reasons": list(guard["blocking_reasons"]),
            "sources": guard["sources"],
        }
    )
    window = _score_window(samples)
    guard["convergence"] = {
        **window,
        "streak_target": CONVERGENCE_STREAK_TARGET,
        "window_target": CONVERGENCE_WINDOW_TARGET,
        "recommendation": (
            "observe-only"
            if window["converged"]
            else "continue-refresh"
            if all_passed
            else "refresh-facts-and-release-gates"
        ),
    }
    guard["trend"] = (
        "stable"
        if window["converged"]
        else "converging"
        if all_passed and window["consecutive_pass_count"] > 0
        else "diverging"
    )
    guard["next_action"] = guard["convergence"]["recommendation"]

    if write_outputs:
        _write_history(samples)
        atomic_write_json(STATUS_PATH, guard)

    guard["history_path"] = str(HISTORY_PATH)
    guard["status_path"] = str(STATUS_PATH)
    guard["history"] = {
        "sample_count": len(samples),
        "latest_sample": samples[-1] if samples else {},
    }
    return guard


def load_fact_gate_convergence_history(limit: int = 20) -> dict[str, Any]:
    history = _load_history()
    samples = list(history.get("samples") or [])
    return {
        "version": history.get("version", 1),
        "sample_count": len(samples),
        "samples": samples[-limit:],
    }


if __name__ == "__main__":
    print(json.dumps(run_fact_gate_convergence(write_outputs=True), ensure_ascii=False, indent=2))
