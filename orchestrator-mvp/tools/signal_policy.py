from __future__ import annotations

from typing import Any, Iterable


POLICY_VERSION = "v1"

RUNTIME_BLOCKER_EFFECT = "degrade_freeze_recovery"
MATURITY_EFFECT = "dashboard_weekly_trend"
RELEASE_GATE_EFFECT = "stage_gate_release_claims"
ADVISORY_EFFECT = "observe_only"

RUNTIME_BLOCKER_RULES: dict[str, dict[str, Any]] = {
    "daemon_unhealthy": {
        "effect": RUNTIME_BLOCKER_EFFECT,
        "affects_runtime": True,
        "affects_release": True,
        "affects_reporting": True,
        "whitelisted": True,
    },
    "control_layer_unstable": {
        "effect": RUNTIME_BLOCKER_EFFECT,
        "affects_runtime": True,
        "affects_release": True,
        "affects_reporting": True,
        "whitelisted": True,
    },
    "core_state_corrupted": {
        "effect": RUNTIME_BLOCKER_EFFECT,
        "affects_runtime": True,
        "affects_release": True,
        "affects_reporting": True,
        "whitelisted": True,
    },
    "core_state_unwritable": {
        "effect": RUNTIME_BLOCKER_EFFECT,
        "affects_runtime": True,
        "affects_release": True,
        "affects_reporting": True,
        "whitelisted": True,
    },
    "critical_tool_health_failure": {
        "effect": RUNTIME_BLOCKER_EFFECT,
        "affects_runtime": True,
        "affects_release": True,
        "affects_reporting": True,
        "whitelisted": True,
    },
    "verification_hard_block": {
        "effect": RUNTIME_BLOCKER_EFFECT,
        "affects_runtime": True,
        "affects_release": True,
        "affects_reporting": True,
        "whitelisted": True,
    },
}

MATURITY_RULES: dict[str, dict[str, Any]] = {
    "quality_attention": {
        "effect": MATURITY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
    "autonomy_stage3": {
        "effect": MATURITY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
    "ai_testing_degraded": {
        "effect": MATURITY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
    "queued_task_backlog": {
        "effect": MATURITY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
    "strategy_reinforcement_needed": {
        "effect": MATURITY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
}

RELEASE_RULES: dict[str, dict[str, Any]] = {
    "release_gate_not_confirmed": {
        "effect": RELEASE_GATE_EFFECT,
        "affects_runtime": False,
        "affects_release": True,
        "affects_reporting": True,
    },
    "stage4_confirmation_pending": {
        "effect": RELEASE_GATE_EFFECT,
        "affects_runtime": False,
        "affects_release": True,
        "affects_reporting": True,
    },
    "verification_delay": {
        "effect": RELEASE_GATE_EFFECT,
        "affects_runtime": False,
        "affects_release": True,
        "affects_reporting": True,
    },
    "sampled_release_blocked": {
        "effect": RELEASE_GATE_EFFECT,
        "affects_runtime": False,
        "affects_release": True,
        "affects_reporting": True,
    },
    "tasks_waiting_approval": {
        "effect": RELEASE_GATE_EFFECT,
        "affects_runtime": False,
        "affects_release": True,
        "affects_reporting": True,
    },
}

ADVISORY_RULES: dict[str, dict[str, Any]] = {
    "artifact_audit": {
        "effect": ADVISORY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
    "reality_dashboard": {
        "effect": ADVISORY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
    "fact_consistency": {
        "effect": ADVISORY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
    },
}

RUNTIME_BLOCKER_STATES = {
    "broken",
    "critical",
    "corrupted",
    "error",
    "failed",
    "fatal",
    "offline",
    "stale",
    "stopped",
    "unhealthy",
    "unstable",
    "unwritable",
}

RUNTIME_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    ("permissionerror", "core_state_unwritable"),
    ("permission denied", "core_state_unwritable"),
    ("read-only", "core_state_unwritable"),
    ("readonly", "core_state_unwritable"),
    ("cannot write", "core_state_unwritable"),
    ("write failed", "core_state_unwritable"),
    ("json decode", "core_state_corrupted"),
    ("decodeerror", "core_state_corrupted"),
    ("parse error", "core_state_corrupted"),
    ("corrupt", "core_state_corrupted"),
    ("checksum", "core_state_corrupted"),
    ("digest mismatch", "core_state_corrupted"),
    ("tool health", "critical_tool_health_failure"),
    ("verification hard", "verification_hard_block"),
    ("compileall", "verification_hard_block"),
    ("platform_runtime", "verification_hard_block"),
    ("daemon", "daemon_unhealthy"),
    ("heartbeat expired", "daemon_unhealthy"),
    ("control layer", "control_layer_unstable"),
    ("control_layer", "control_layer_unstable"),
)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _normalize_code(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("code") or value.get("name") or value.get("id") or value.get("signal")
    return str(value or "").strip()


def _normalize_state(value: Any) -> str:
    return str(value or "").strip().lower()


def is_runtime_blocker_state(value: Any) -> bool:
    return _normalize_state(value) in RUNTIME_BLOCKER_STATES


def runtime_blocker_codes_from_error(error: Any) -> list[str]:
    text = str(error or "").strip().lower()
    if not text:
        return []
    matches: list[str] = []
    for needle, code in RUNTIME_ERROR_HINTS:
        if needle in text and code not in matches:
            matches.append(code)
    return matches


def _build_signal(code: str, *, category: str, source: str, detail: Any = None) -> dict[str, Any]:
    rule_maps = {
        "runtime_blocker": RUNTIME_BLOCKER_RULES,
        "maturity": MATURITY_RULES,
        "release": RELEASE_RULES,
        "advisory": ADVISORY_RULES,
    }
    rule = rule_maps.get(category, {}).get(code) or {
        "effect": ADVISORY_EFFECT,
        "affects_runtime": False,
        "affects_release": False,
        "affects_reporting": True,
        "whitelisted": False,
    }
    return {
        "code": code,
        "category": category,
        "source": source,
        "detail": detail,
        "effect": rule.get("effect"),
        "affects_runtime": bool(rule.get("affects_runtime")),
        "affects_release": bool(rule.get("affects_release")),
        "affects_reporting": bool(rule.get("affects_reporting", True)),
        "whitelisted": bool(rule.get("whitelisted", False)),
    }


def _build_dashboard(runtime_blockers: list[dict[str, Any]], maturity_signals: list[dict[str, Any]], release_gate_signals: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "Runtime": {
            "status": "blocked" if runtime_blockers else "healthy",
            "signal_count": len(runtime_blockers),
            "signals": runtime_blockers,
        },
        "Maturity": {
            "status": "attention" if maturity_signals else "ok",
            "signal_count": len(maturity_signals),
            "signals": maturity_signals,
        },
        "Release Readiness": {
            "status": "attention" if release_gate_signals else "ready",
            "signal_count": len(release_gate_signals),
            "signals": release_gate_signals,
        },
    }


def summarize_signal_policy(
    *,
    runtime_blockers: Iterable[str] = (),
    maturity_signals: Iterable[str] = (),
    release_gate_signals: Iterable[str] = (),
    advisory_signals: Iterable[str] = (),
    source: str = "live",
) -> dict[str, Any]:
    runtime_candidates = _dedupe(_normalize_code(item) for item in runtime_blockers)
    maturity_items = _dedupe(_normalize_code(item) for item in maturity_signals)
    release_items = _dedupe(_normalize_code(item) for item in release_gate_signals)
    advisory_items = _dedupe(_normalize_code(item) for item in advisory_signals)
    runtime_blocker_items = [
        _build_signal(item, category="runtime_blocker", source=source)
        for item in runtime_candidates
        if item in RUNTIME_BLOCKER_RULES
    ]
    rejected_runtime_blockers = [
        _build_signal(item, category="runtime_blocker", source=source)
        for item in runtime_candidates
        if item not in RUNTIME_BLOCKER_RULES
    ]
    maturity_signal_items = [
        _build_signal(item, category="maturity", source=source)
        for item in maturity_items
    ]
    release_gate_signal_items = [
        _build_signal(item, category="release", source=source)
        for item in release_items
    ]
    advisory_signal_items = [
        _build_signal(item, category="advisory", source=source)
        for item in advisory_items
    ]
    return {
        "policy_version": POLICY_VERSION,
        "source": source,
        "dimensions": {
            "stage": "autonomy",
            "health": "runtime",
            "release": "release_readiness",
        },
        "runtime_blockers": runtime_blocker_items,
        "runtime_blocker_count": len(runtime_blocker_items),
        "rejected_runtime_blockers": rejected_runtime_blockers,
        "rejected_runtime_blocker_count": len(rejected_runtime_blockers),
        "runtime_effect": RUNTIME_BLOCKER_EFFECT,
        "maturity_signals": maturity_signal_items,
        "maturity_signal_count": len(maturity_signal_items),
        "maturity_effect": MATURITY_EFFECT,
        "release_gate_signals": release_gate_signal_items,
        "release_gate_signal_count": len(release_gate_signal_items),
        "release_gate_effect": RELEASE_GATE_EFFECT,
        "advisory_signals": advisory_signal_items,
        "advisory_signal_count": len(advisory_signal_items),
        "advisory_effect": ADVISORY_EFFECT,
        "dashboard": _build_dashboard(runtime_blocker_items, maturity_signal_items, release_gate_signal_items),
    }
