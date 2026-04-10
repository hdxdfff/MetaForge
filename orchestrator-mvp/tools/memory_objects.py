from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.context_cache import load_cache, purge_stale_cache_entries
from tools.io_utils import atomic_write_text

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT.parent
DATA = ROOT / "data"

OBJECTS_PATH = DATA / "memory_objects.jsonl"
CANDIDATES_PATH = DATA / "memory_candidates.jsonl"
ACTIVE_SNAPSHOT = WORKSPACE_ROOT / "METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json"
ACTIVE_DIALOGUE = DATA / "dialogue_memory.json"
MEMORY_MODEL = WORKSPACE_ROOT / "METAFORGE_OS_MEMORY_MODEL.md"
BUILD_REPORT = ROOT / "build-report.json"
SOAK_REPORT_GLOB = DATA / "soak_report_*.json"
RUNTIME_EPOCH = DATA / "runtime_epoch.json"
FACTORY_DAEMON_STATE = DATA / "factory_daemon_state.json"

MEMORY_TYPES = {"fact", "procedure", "decision", "failure_fix", "handoff"}
AUTHORITY_ORDER = {"verified": 3, "derived": 2, "unverified": 1}
STATUS_ORDER = {"active": 3, "candidate": 2, "superseded": 1, "archived": 0}
PROMOTION_THRESHOLD_BY_TYPE = {
    "failure_fix": 0.9,
    "procedure": 0.88,
    "decision": 0.92,
    "fact": 0.94,
    "handoff": 0.96,
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _load_json_any(path: Path) -> Any:
    return _load_json(path, {})


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _save_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(item, ensure_ascii=False) for item in items)
    if content:
        content += "\n"
    atomic_write_text(path, content, encoding="utf-8")


def _trim(value: Any, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "memory"


def _listify(value: Any, *, limit: int = 8, item_limit: int = 160) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = _trim(raw, item_limit)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _parse_dt(value: Any) -> datetime:
    text = _trim(value, 64)
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _future_iso_timestamp(value: Any, *, hours: int = 72) -> str:
    base = _parse_dt(value)
    now = datetime.now(timezone.utc)
    if base == datetime.min.replace(tzinfo=timezone.utc) or base < now:
        base = now
    return (base + timedelta(hours=hours)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_expired(item: dict[str, Any]) -> bool:
    validity = item.get("validity") if isinstance(item.get("validity"), dict) else {}
    expires_at = _trim(validity.get("expires_at"), 64)
    if not expires_at:
        return False
    return _parse_dt(expires_at) < datetime.now(timezone.utc)


def _current_memory_revision() -> str:
    parts: list[str] = []
    for path in [
        ROOT / "tools" / "context_builder.py",
        ROOT / "tools" / "memory_objects.py",
        DATA / "memory_objects.jsonl",
        DATA / "memory_candidates.jsonl",
    ]:
        if not path.exists():
            parts.append(f"{path.name}:missing")
            continue
        stat = path.stat()
        parts.append(f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}")
    return "|".join(parts)


def _duplicate_ids(items: list[dict[str, Any]], key_name: str) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for item in items:
        value = _trim(item.get(key_name), 160)
        if not value:
            continue
        if value in seen and value not in dupes:
            dupes.append(value)
            continue
        seen.add(value)
    return dupes


def _normalize_scope(scope: Any) -> dict[str, list[str]]:
    payload = scope if isinstance(scope, dict) else {}
    return {
        "system": _listify(payload.get("system"), limit=4, item_limit=80),
        "workspace": _listify(payload.get("workspace"), limit=4, item_limit=220),
        "component": _listify(payload.get("component"), limit=8, item_limit=120),
        "task_domain": _listify(payload.get("task_domain"), limit=8, item_limit=120),
    }


def _normalize_validity(validity: Any) -> dict[str, Any]:
    payload = validity if isinstance(validity, dict) else {}
    trigger = payload.get("trigger")
    if trigger is None:
        trigger = []
    elif not isinstance(trigger, list):
        trigger = [trigger]
    return {
        "kind": _trim(payload.get("kind") or "revalidate_on_change", 80),
        "trigger": _listify(trigger, limit=8, item_limit=120),
        "expires_at": payload.get("expires_at"),
    }


def _memory_id(memory_type: str, title: str, existing: set[str] | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = f"mem_{memory_type}_{_slug(title)[:48]}_{stamp}"
    if not existing or base not in existing:
        return base
    idx = 2
    while f"{base}_{idx}" in existing:
        idx += 1
    return f"{base}_{idx}"


def _extract_runtime_failure_fix_seed() -> dict[str, Any] | None:
    runtime_epoch = _load_json_any(RUNTIME_EPOCH)
    daemon_state = _load_json_any(FACTORY_DAEMON_STATE)
    risk_reasons: list[str] = []
    if isinstance(runtime_epoch, dict):
        risk_reasons = _listify(runtime_epoch.get("continuity_risk_reasons"), limit=8, item_limit=160)
    if not risk_reasons and isinstance(daemon_state, dict):
        risk_reasons = _listify(daemon_state.get("continuity_risk_reasons"), limit=8, item_limit=160)
    if not risk_reasons:
        return None

    symptom = risk_reasons[0]
    return {
        "memory_id": "mem_failurefix_state_write_permission_denied_continuity",
        "memory_type": "failure_fix",
        "title": "State write permission denials weaken trustworthy continuity",
        "summary": "Persisted state writes can fail while liveness continues, so continuity must include persistence trust.",
        "scope": {
            "system": ["metaforge"],
            "workspace": [WORKSPACE_ROOT.as_posix()],
            "component": ["factory_daemon", "state"],
            "task_domain": ["continuity", "persistence"],
        },
        "tags": ["permissionerror", "continuity", "persistence", "state-write"],
        "authority": "verified",
        "status": "active",
        "source_refs": [
            "D:\\codex\\orchestrator-mvp\\data\\runtime_epoch.json",
            "D:\\codex\\orchestrator-mvp\\data\\factory_daemon_state.json",
        ],
        "evidence_refs": [
            "state_write_permission_denied",
            "evidence_write_failures_last_24h",
        ],
        "validity": {
            "kind": "revalidate_on_change",
            "trigger": [
                "runtime_epoch_changed",
                "daemon_state_changed",
                "persistence_path_changed",
            ],
            "expires_at": None,
        },
        "reuse_score": 0.97,
        "priority": "high",
        "failure_fix": {
            "symptom": symptom,
            "root_cause": "State persistence failure was not always treated as a continuity risk input.",
            "trigger_conditions": [
                "Windows file permission issue",
                "state file locked or protected",
                "evidence write failure count increases",
            ],
            "fix": [
                "Treat persistence write failures as continuity risk input.",
                "Record degraded trust state when writes fail.",
                "Keep liveness and trustworthy continuity separate.",
            ],
            "verification": [
                "Continuity mode reflects persistence failure.",
                "Epoch trust semantics reflect state persistence outcome.",
            ],
            "prevention": [
                "Preflight write permission checks.",
                "Atomic replace on state writes.",
                "Track persistence error counters and alert on recurrence.",
            ],
            "recurrence_risk": "medium",
        },
    }


def _extract_build_report_candidates() -> list[dict[str, Any]]:
    payload = _load_json_any(BUILD_REPORT)
    if not isinstance(payload, dict):
        return []

    candidates: list[dict[str, Any]] = []
    build_ready = bool(payload.get("build_ready"))
    build_success = bool(payload.get("build_success"))
    managed = payload.get("managed_resolution") if isinstance(payload.get("managed_resolution"), dict) else {}
    docker_detail = _trim(managed.get("docker_detail"), 500)
    recommended_backend = _trim(managed.get("recommended_backend"), 64)
    host_build_ready = bool(payload.get("host_build_ready"))
    toolchain = payload.get("toolchain") if isinstance(payload.get("toolchain"), dict) else {}
    missing_tools = [
        name
        for name in ["nasm", "gcc", "i686_elf_gcc", "i686_elf_ld", "ld", "qemu_system_i386", "make"]
        if not toolchain.get(name)
    ]

    if not build_ready or not build_success:
        candidates.append(
            {
                "candidate_id": "cand_failurefix_build_ready_requires_toolchain_and_docker",
                "derived_from": ["D:\\codex\\orchestrator-mvp\\build-report.json"],
                "proposed_memory_type": "failure_fix",
                "confidence": 0.93,
                "review_status": "pending",
                "proposed_object": {
                    "memory_type": "failure_fix",
                    "title": "Build readiness must gate on toolchain and Docker daemon availability",
                    "summary": "Host-toolchain absence and Docker daemon unavailability should block build readiness claims.",
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [WORKSPACE_ROOT.as_posix()],
                        "component": ["build", "toolchain", "docker"],
                        "task_domain": ["toyos", "verification"],
                    },
                    "tags": ["build", "docker", "toolchain", "readiness"],
                    "authority": "derived",
                    "status": "candidate",
                    "source_refs": ["build-report.json"],
                    "evidence_refs": [
                        "build_ready=false",
                        "build_success=false",
                        "docker_daemon_ready=false",
                    ],
                    "validity": {
                        "kind": "revalidate_on_change",
                        "trigger": [
                            "build_entry_changed",
                            "docker_daemon_changed",
                            "toolchain_changed",
                        ],
                        "expires_at": None,
                    },
                    "reuse_score": 0.91,
                    "priority": "high",
                    "failure_fix": {
                        "symptom": "build readiness reported false",
                        "root_cause": "Missing host toolchain and unavailable Docker daemon were not both gated before readiness claims.",
                        "trigger_conditions": [
                            "nasm absent",
                            "gcc absent",
                            "docker daemon unavailable",
                        ],
                        "fix": [
                            "Gate build readiness on toolchain and daemon readiness.",
                            "Avoid host-only success claims when required tooling is absent.",
                            "Route to a clear unavailable state when build backend is not usable.",
                        ],
                        "verification": [
                            "build_ready remains false until prerequisites are present.",
                            "recommended_backend is not treated as runnable when daemon is down.",
                        ],
                        "prevention": [
                            "Add preflight toolchain and daemon checks.",
                            "Expose missing tool list in build status.",
                        ],
                        "recurrence_risk": "medium",
                    },
                },
            }
        )

    if not host_build_ready:
        candidates.append(
            {
                "candidate_id": "cand_procedure_build_preflight_toolchain_daemon",
                "derived_from": ["D:\\codex\\orchestrator-mvp\\build-report.json"],
                "proposed_memory_type": "procedure",
                "confidence": 0.88,
                "review_status": "pending",
                "proposed_object": {
                    "memory_type": "procedure",
                    "title": "Preflight ToyOS build before claiming readiness",
                    "summary": "Probe toolchain and Docker daemon before any ToyOS build verdict.",
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [WORKSPACE_ROOT.as_posix()],
                        "component": ["build", "verification"],
                        "task_domain": ["toyos", "release"],
                    },
                    "tags": ["procedure", "build", "preflight", "docker"],
                    "authority": "derived",
                    "status": "candidate",
                    "source_refs": ["build-report.json"],
                    "evidence_refs": missing_tools[:6] + ([docker_detail] if docker_detail else []),
                    "validity": {
                        "kind": "revalidate_on_change",
                        "trigger": ["build_entry_changed"],
                        "expires_at": None,
                    },
                    "reuse_score": 0.86,
                    "priority": "medium",
                    "procedure": {
                        "goal": "Avoid false build readiness claims.",
                        "preconditions": [
                            "Workspace is set.",
                            "Build report exists.",
                        ],
                        "steps": [
                            "Read the current build report.",
                            "Check required toolchain executables.",
                            "Check Docker daemon readiness.",
                            "Only claim readiness if all required checks pass.",
                        ],
                        "expected_outputs": [
                            "build-report.json",
                            "toolchain probe result",
                            "daemon readiness result",
                        ],
                        "validation_steps": [
                            "Confirm missing_tools is empty or explicitly tolerated.",
                            "Confirm docker daemon is reachable if Docker is selected.",
                        ],
                        "failure_signals": [
                            "build_ready is false",
                            "host_build_ready is false",
                            "docker daemon cannot be reached",
                        ],
                    },
                },
            }
        )

    if docker_detail and recommended_backend:
        candidates.append(
            {
                "candidate_id": "cand_fact_build_backend_unavailable_details",
                "derived_from": ["D:\\codex\\orchestrator-mvp\\build-report.json"],
                "proposed_memory_type": "fact",
                "confidence": 0.8,
                "review_status": "pending",
                "proposed_object": {
                    "memory_type": "fact",
                    "title": "Build backend availability detail",
                    "summary": "The recommended build backend is unavailable because the Docker daemon cannot be reached.",
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [WORKSPACE_ROOT.as_posix()],
                        "component": ["build", "docker"],
                        "task_domain": ["toyos"],
                    },
                    "tags": ["build", "docker", "availability"],
                    "authority": "derived",
                    "status": "candidate",
                    "source_refs": ["build-report.json"],
                    "evidence_refs": [docker_detail],
                    "validity": {
                        "kind": "revalidate_on_change",
                        "trigger": ["docker_daemon_changed"],
                        "expires_at": None,
                    },
                    "reuse_score": 0.74,
                    "priority": "medium",
                    "fact": {
                        "subject": "build_backend_availability",
                        "statement": "The recommended build backend is unavailable until the Docker daemon is reachable.",
                        "source_of_truth": "build-report.json",
                        "verification_method": "report_match",
                    },
                },
            }
        )

    return candidates


def _extract_soak_report_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in sorted(DATA.glob("soak_report_*.json")):
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        focus = payload.get("focus_artifact")
        if not isinstance(focus, dict):
            continue
        verification_status = _trim(focus.get("verification_status"), 64)
        build_success = bool(focus.get("build_success"))
        artifact_audit_passed = bool(focus.get("artifact_audit_passed"))
        pending_checks = _listify(focus.get("verification_pending_checks"), limit=12, item_limit=160)
        artifact_id = _trim(focus.get("artifact_id"), 120) or "artifact"
        artifact_path = _trim(focus.get("artifact_path"), 260)
        permission_errors = int(focus.get("permission_error_count_tail200") or 0)
        label = _trim(payload.get("label"), 160)

        if verification_status == "attention" or pending_checks:
            candidates.append(
                {
                    "candidate_id": f"cand_procedure_soak_verification_gate_{_slug(label or artifact_id)}",
                    "derived_from": [str(path)],
                    "proposed_memory_type": "procedure",
                    "confidence": 0.87,
                    "review_status": "pending",
                    "proposed_object": {
                        "memory_type": "procedure",
                        "title": "Treat soak verification pending checks as gate blockers",
                        "summary": f"Soak runs for {artifact_id} should not be considered clean while verification remains attention.",
                        "scope": {
                            "system": ["metaforge"],
                            "workspace": [artifact_path or WORKSPACE_ROOT.as_posix()],
                            "component": ["soak", "verification"],
                            "task_domain": ["toyos", "continuity"],
                        },
                        "tags": ["soak", "verification", "gate", "attention"],
                        "authority": "derived",
                        "status": "candidate",
                        "source_refs": [path.name],
                        "evidence_refs": pending_checks[:8] or [verification_status],
                        "validity": {
                            "kind": "revalidate_on_change",
                            "trigger": ["soak_report_changed"],
                            "expires_at": None,
                        },
                        "reuse_score": 0.83,
                        "priority": "medium",
                        "procedure": {
                            "goal": "Avoid treating soak attention states as release-ready signals.",
                            "preconditions": [
                                "A soak report exists.",
                                "The focus artifact path is known.",
                            ],
                            "steps": [
                                "Read the soak report for the current artifact.",
                                "Inspect verification_status and verification_pending_checks.",
                                "Do not promote the artifact to pass while pending checks remain.",
                                "Attach explicit evidence notes to any delivery claim.",
                            ],
                            "expected_outputs": [
                                "soak report",
                                "pending check list",
                                "validation notes",
                            ],
                            "validation_steps": [
                                "Confirm verification_status is not attention before release claim.",
                                "Confirm pending_checks is empty before promotion.",
                            ],
                            "failure_signals": [
                                "verification_status is attention",
                                "pending checks are non-empty",
                            ],
                        },
                    },
                }
            )

        if build_success and artifact_audit_passed and permission_errors == 0:
            candidates.append(
                {
                    "candidate_id": f"cand_fact_soak_artifact_baseline_{_slug(label or artifact_id)}",
                    "derived_from": [str(path)],
                    "proposed_memory_type": "fact",
                    "confidence": 0.81,
                    "review_status": "pending",
                    "proposed_object": {
                        "memory_type": "fact",
                        "title": "Soak artifact baseline is build-success plus clean audit",
                        "summary": f"{artifact_id} currently reports build success with artifact audit passing and no permission errors in the tail window.",
                        "scope": {
                            "system": ["metaforge"],
                            "workspace": [artifact_path or WORKSPACE_ROOT.as_posix()],
                            "component": ["soak", "artifact"],
                            "task_domain": ["toyos", "delivery"],
                        },
                        "tags": ["soak", "artifact", "audit", "build"],
                        "authority": "derived",
                        "status": "candidate",
                        "source_refs": [path.name],
                        "evidence_refs": [
                            "build_success=true",
                            "artifact_audit_passed=true",
                            "permission_error_count_tail200=0",
                        ],
                        "validity": {
                            "kind": "revalidate_on_change",
                            "trigger": ["soak_report_changed"],
                            "expires_at": None,
                        },
                        "reuse_score": 0.72,
                        "priority": "low",
                        "fact": {
                            "subject": "artifact_baseline",
                            "statement": f"{artifact_id} reports build success with clean artifact audit in the sampled soak report.",
                            "source_of_truth": path.name,
                            "verification_method": "report_match",
                        },
                    },
                }
            )

    return candidates


def harvest_memory_candidates() -> dict[str, Any]:
    discovered: list[dict[str, Any]] = []
    discovered.extend(_extract_build_report_candidates())
    discovered.extend(_extract_soak_report_candidates())
    runtime_failure_fix = _extract_runtime_failure_fix_seed()
    if runtime_failure_fix:
        discovered.append(
            {
                "candidate_id": "cand_failurefix_runtime_state_persistence_trust",
                "derived_from": [
                    "D:\\codex\\orchestrator-mvp\\data\\runtime_epoch.json",
                    "D:\\codex\\orchestrator-mvp\\data\\factory_daemon_state.json",
                ],
                "proposed_memory_type": "failure_fix",
                "confidence": 0.95,
                "review_status": "pending",
                "proposed_object": runtime_failure_fix,
            }
        )

    ingested = 0
    for candidate in discovered:
        if not isinstance(candidate.get("proposed_object"), dict):
            continue
        append_candidate(candidate)
        ingested += 1

    return {
        "status": "harvested",
        "candidate_count": len(load_candidates()),
        "ingested": ingested,
        "store_path": str(CANDIDATES_PATH),
        "sources": [
            str(BUILD_REPORT),
            str(RUNTIME_EPOCH),
            str(FACTORY_DAEMON_STATE),
            str(DATA),
        ],
    }


def _common_object(
    payload: dict[str, Any],
    *,
    memory_type: str,
    authority: str,
    status: str,
    existing: set[str] | None = None,
) -> dict[str, Any]:
    title = _trim(payload.get("title"), 200)
    summary = _trim(payload.get("summary"), 1200)
    if not title:
        raise ValueError("memory title is required")
    if not summary:
        raise ValueError("memory summary is required")

    memory_id = _trim(payload.get("memory_id"), 160) or _memory_id(memory_type, title, existing)
    scope = _normalize_scope(payload.get("scope"))
    tags = _listify(payload.get("tags"), limit=12, item_limit=80)
    source_refs = _listify(payload.get("source_refs"), limit=20, item_limit=300)
    evidence_refs = _listify(payload.get("evidence_refs"), limit=20, item_limit=300)
    conflicts_with = _listify(payload.get("conflicts_with"), limit=12, item_limit=120)
    validity = _normalize_validity(payload.get("validity"))
    try:
        reuse_score = float(payload.get("reuse_score") or 0.5)
    except Exception:
        reuse_score = 0.5

    item = {
        "memory_id": memory_id,
        "memory_type": memory_type,
        "title": title,
        "summary": summary,
        "scope": scope,
        "tags": tags,
        "authority": _trim(payload.get("authority") or authority, 32),
        "status": _trim(payload.get("status") or status, 32),
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "created_at": _trim(payload.get("created_at") or _utc(), 64),
        "updated_at": _trim(payload.get("updated_at") or _utc(), 64),
        "last_verified_at": _trim(payload.get("last_verified_at"), 64) or None,
        "validity": validity,
        "reuse_score": max(0.0, min(1.0, reuse_score)),
        "priority": _trim(payload.get("priority") or "normal", 24),
        "superseded_by": payload.get("superseded_by"),
        "conflicts_with": conflicts_with,
    }
    if item["authority"] == "verified" and not item["last_verified_at"]:
        item["last_verified_at"] = item["updated_at"]

    typed_payload = payload.get(memory_type)
    if not isinstance(typed_payload, dict):
        typed_payload = {}
        for key in MEMORY_TYPES:
            candidate = payload.get(key)
            if isinstance(candidate, dict):
                typed_payload = candidate
                break
    item[memory_type] = typed_payload
    return item


def normalize_verified_object(payload: dict[str, Any], *, existing: set[str] | None = None) -> dict[str, Any]:
    memory_type = _trim(payload.get("memory_type"), 32)
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"unsupported memory_type: {memory_type}")
    return _common_object(payload, memory_type=memory_type, authority="verified", status="active", existing=existing)


def normalize_candidate_object(payload: dict[str, Any], *, existing: set[str] | None = None) -> dict[str, Any]:
    memory_type = _trim(payload.get("proposed_memory_type") or payload.get("memory_type"), 32)
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"unsupported proposed_memory_type: {memory_type}")
    proposed = payload.get("proposed_object") if isinstance(payload.get("proposed_object"), dict) else dict(payload)
    proposed["memory_type"] = memory_type
    item = _common_object(proposed, memory_type=memory_type, authority="derived", status="candidate", existing=existing)
    item["authority"] = "derived"
    item["status"] = "candidate"
    item["last_verified_at"] = None
    candidate_id = _trim(payload.get("candidate_id"), 160) or _memory_id("candidate", item["title"], existing)
    try:
        confidence = float(payload.get("confidence") or 0.5)
    except Exception:
        confidence = 0.5
    item.update(
        {
            "candidate_id": candidate_id,
            "derived_from": _listify(payload.get("derived_from"), limit=16, item_limit=300),
            "confidence": max(0.0, min(1.0, confidence)),
            "review_status": _trim(payload.get("review_status") or "pending", 24),
            "proposed_memory_type": memory_type,
            "proposed_title": item["title"],
            "proposed_object": proposed,
        }
    )
    return item


def _archive_expired_verified_handoffs(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    changed = False
    now = _utc()
    replacement: list[dict[str, Any]] = []
    for item in items:
        if (
            isinstance(item, dict)
            and item.get("memory_type") == "handoff"
            and item.get("status") == "active"
            and _is_expired(item)
        ):
            archived = dict(item)
            archived["status"] = "archived"
            archived["updated_at"] = now
            handoff_payload = archived.get("handoff") if isinstance(archived.get("handoff"), dict) else {}
            archived["handoff"] = {
                **handoff_payload,
                "expired_at": (archived.get("validity") or {}).get("expires_at"),
                "archive_reason": "validity_expired",
            }
            replacement.append(archived)
            changed = True
            continue
        replacement.append(item)
    return replacement, changed


def load_verified_objects() -> list[dict[str, Any]]:
    items = _load_jsonl(OBJECTS_PATH)
    replacement, changed = _archive_expired_verified_handoffs(items)
    if changed:
        _save_jsonl(OBJECTS_PATH, replacement)
    return replacement


def load_candidates() -> list[dict[str, Any]]:
    return _load_jsonl(CANDIDATES_PATH)


def summarize_memory_objects() -> dict[str, Any]:
    objects = load_verified_objects()
    candidates = load_candidates()
    counts: dict[str, int] = {}
    for item in objects:
        key = _trim(item.get("memory_type"), 32) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    recent = sorted(objects, key=lambda item: (_parse_dt(item.get("updated_at")), item.get("memory_id") or ""), reverse=True)
    active_handoffs = [
        item
        for item in recent
        if item.get("memory_type") == "handoff" and item.get("status") == "active" and not _is_expired(item)
    ]
    return {
        "status": "ready" if objects else "empty",
        "object_count": len(objects),
        "candidate_count": len(candidates),
        "counts_by_type": counts,
        "recent_verified": [
            {
                "memory_id": item.get("memory_id"),
                "memory_type": item.get("memory_type"),
                "title": item.get("title"),
                "updated_at": item.get("updated_at"),
                "reuse_score": item.get("reuse_score"),
            }
            for item in recent[:8]
        ],
        "active_handoffs": [
            {
                "memory_id": item.get("memory_id"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "updated_at": item.get("updated_at"),
            }
            for item in active_handoffs[:4]
        ],
    }


def memory_integrity_report() -> dict[str, Any]:
    objects = load_verified_objects()
    candidates = load_candidates()
    current_revision = _current_memory_revision()
    purge_stale_cache_entries(memory_revision=current_revision)
    cache = load_cache()
    stale_cache_entries: list[dict[str, Any]] = []
    for key, entry in (cache.get("entries") or {}).items():
        if not isinstance(entry, dict):
            continue
        entry_revision = _trim(entry.get("memory_revision"), 240)
        if entry_revision != current_revision:
            stale_cache_entries.append(
                {
                    "key": key,
                    "updated_at": entry.get("updated_at"),
                    "memory_revision": entry_revision,
                }
            )

    expired_handoffs = [
        {
            "memory_id": item.get("memory_id"),
            "title": item.get("title"),
            "expires_at": (item.get("validity") or {}).get("expires_at"),
            "status": item.get("status"),
            "authority": item.get("authority"),
        }
        for item in objects
        if item.get("memory_type") == "handoff" and item.get("status") == "active" and _is_expired(item)
    ]
    duplicate_verified_ids = _duplicate_ids(objects, "memory_id")
    duplicate_candidate_ids = _duplicate_ids(candidates, "candidate_id")
    duplicate_candidate_memory_ids = _duplicate_ids(
        [
            item.get("proposed_object")
            for item in candidates
            if isinstance(item.get("proposed_object"), dict)
        ],
        "memory_id",
    )
    return {
        "status": "ok" if not (stale_cache_entries or expired_handoffs or duplicate_verified_ids or duplicate_candidate_ids) else "attention",
        "current_memory_revision": current_revision,
        "verified_object_count": len(objects),
        "candidate_count": len(candidates),
        "duplicate_verified_memory_ids": duplicate_verified_ids,
        "duplicate_candidate_ids": duplicate_candidate_ids,
        "duplicate_candidate_memory_ids": duplicate_candidate_memory_ids,
        "expired_handoffs": expired_handoffs,
        "stale_cache_entry_count": len(stale_cache_entries),
        "stale_cache_entries": stale_cache_entries[:12],
        "cache_entry_count": len(cache.get("entries") or {}),
    }


def upsert_verified_object(payload: dict[str, Any]) -> dict[str, Any]:
    objects = load_verified_objects()
    existing_ids = {item.get("memory_id") for item in objects if isinstance(item, dict)}
    item = normalize_verified_object(payload, existing=existing_ids)
    replacement = [entry for entry in objects if entry.get("memory_id") != item["memory_id"]]
    replacement.append(item)
    replacement.sort(key=lambda entry: (_parse_dt(entry.get("updated_at")), entry.get("memory_id") or ""), reverse=True)
    _save_jsonl(OBJECTS_PATH, replacement)
    return item


def append_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = load_candidates()
    existing_ids = {item.get("candidate_id") for item in candidates if isinstance(item, dict)}
    item = normalize_candidate_object(payload, existing=existing_ids)
    replacement = [entry for entry in candidates if entry.get("candidate_id") != item["candidate_id"]]
    replacement.append(item)
    replacement.sort(key=lambda entry: (_parse_dt(entry.get("updated_at")), entry.get("candidate_id") or ""), reverse=True)
    _save_jsonl(CANDIDATES_PATH, replacement)
    return item


def _extract_text(item: dict[str, Any]) -> str:
    parts = [item.get("title"), item.get("summary"), " ".join(item.get("tags") or [])]
    scope = item.get("scope") or {}
    if isinstance(scope, dict):
        for key in ("workspace", "component", "task_domain", "system"):
            parts.append(" ".join(scope.get(key) or []))
    for key in ("source_refs", "evidence_refs"):
        parts.append(" ".join(item.get(key) or []))
    payload = item.get(item.get("memory_type") or "")
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.append(" ".join(str(part) for part in value))
    return " ".join(part for part in parts if part).lower()


def _tokenize(query: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9_.:-]+", query.lower()) if token]


def _score_item(
    item: dict[str, Any],
    *,
    query: str,
    tokens: list[str],
    workspace: str | None,
    tags: list[str] | None,
    memory_types: list[str] | None,
    include_candidates: bool,
) -> float:
    score = 0.0
    text = _extract_text(item)
    title = _trim(item.get("title"), 240).lower()
    summary = _trim(item.get("summary"), 600).lower()
    item_tags = [tag.lower() for tag in item.get("tags") or []]
    scope = item.get("scope") or {}
    workspaces = [value.lower() for value in (scope.get("workspace") or [])]
    memory_type = str(item.get("memory_type") or "").lower()
    authority = str(item.get("authority") or "unverified").lower()
    status = str(item.get("status") or "").lower()

    if query:
        if query.lower() in title:
            score += 5.0
        if query.lower() in summary:
            score += 3.0
        if query.lower() in text:
            score += 1.5
    for token in tokens:
        if token in title:
            score += 1.75
        if token in summary:
            score += 1.25
        if token in text:
            score += 0.5
        if token in item_tags:
            score += 0.6
        if token in workspaces:
            score += 0.3
    if workspace:
        normalized = workspace.lower()
        if any(normalized in value or value in normalized for value in workspaces):
            score += 2.5
        else:
            score -= 0.4
    if tags:
        wanted = {tag.lower() for tag in tags}
        score += len(wanted.intersection(item_tags)) * 1.1
    if memory_types:
        wanted = {value.lower() for value in memory_types}
        if memory_type in wanted:
            score += 2.0
        else:
            score -= 1.5
    score += AUTHORITY_ORDER.get(authority, 0) * 0.8
    score += STATUS_ORDER.get(status, 0) * 0.2
    score += min(float(item.get("reuse_score") or 0.0), 1.0) * 1.3
    score += min(len(item.get("evidence_refs") or []), 4) * 0.2
    if item.get("conflicts_with"):
        score -= 0.5
    if memory_type == "handoff":
        handoff_tokens = {"handoff", "current", "active", "runtime", "continuity", "dispatch", "bounded", "state"}
        if any(token in handoff_tokens for token in tokens):
            score += 6.0
        if "handoff" in query.lower():
            score += 5.0
        if any(token in {"current", "active", "runtime", "continuity"} for token in tokens):
            score += 2.5
        if status == "active":
            score += 0.8
    if memory_type == "handoff" and _is_expired(item):
        score -= 100.0
    if not include_candidates and authority != "verified":
        score -= 10.0
    return score


def build_memory_pack(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "fact": [],
        "procedure": [],
        "decision": [],
        "failure_fix": [],
        "handoff": [],
    }
    for item in results:
        memory_type = item.get("memory_type")
        if memory_type == "handoff" and _is_expired(item):
            continue
        if memory_type in grouped:
            grouped[memory_type].append(item)
    return {
        "top_fact": grouped["fact"][:3],
        "top_procedures": grouped["procedure"][:3],
        "top_decisions": grouped["decision"][:3],
        "top_failure_fixes": grouped["failure_fix"][:3],
        "active_handoff": grouped["handoff"][:1],
    }


def recall_memory_objects(
    query: str,
    *,
    workspace: str | None = None,
    tags: list[str] | None = None,
    memory_types: list[str] | None = None,
    limit: int = 8,
    include_candidates: bool = False,
) -> dict[str, Any]:
    query = _trim(query, 400)
    tokens = _tokenize(query)
    items = load_verified_objects()
    if include_candidates:
        items = items + load_candidates()
    ranked = [
        (
            item,
            _score_item(
                item,
                query=query,
                tokens=tokens,
                workspace=workspace,
                tags=tags,
                memory_types=memory_types,
                include_candidates=include_candidates,
            ),
        )
        for item in items
        if item.get("memory_type") in MEMORY_TYPES
        and not (item.get("memory_type") == "handoff" and _is_expired(item))
    ]
    ranked.sort(
        key=lambda pair: (
            pair[1],
            _parse_dt(pair[0].get("updated_at") or pair[0].get("last_verified_at")),
            pair[0].get("memory_id") or "",
        ),
        reverse=True,
    )
    results: list[dict[str, Any]] = []
    seen_memory_ids: set[str] = set()
    for item, _score in ranked:
        memory_id = _trim(item.get("memory_id"), 160)
        if memory_id and memory_id in seen_memory_ids:
            continue
        if memory_id:
            seen_memory_ids.add(memory_id)
        results.append(item)
        if len(results) >= max(1, limit):
            break
    return {
        "query": query,
        "filters": {
            "workspace": workspace,
            "tags": tags or [],
            "memory_types": memory_types or [],
            "limit": limit,
            "include_candidates": include_candidates,
        },
        "results": [
            {
                "memory_id": item.get("memory_id"),
                "memory_type": item.get("memory_type"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "scope": item.get("scope"),
                "tags": item.get("tags", []),
                "authority": item.get("authority"),
                "status": item.get("status"),
                "reuse_score": item.get("reuse_score"),
                "updated_at": item.get("updated_at"),
            }
            for item in results
        ],
        "memory_pack": build_memory_pack(results),
    }


def register_candidate_from_object(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = {
        "candidate_id": _trim(payload.get("candidate_id"), 160) or _memory_id("candidate", _trim(payload.get("title"), 80)),
        "derived_from": _listify(payload.get("derived_from"), limit=16, item_limit=300),
        "confidence": max(0.0, min(1.0, float(payload.get("confidence") or 0.5))),
        "review_status": _trim(payload.get("review_status") or "pending", 24),
        "proposed_memory_type": _trim(payload.get("memory_type"), 32),
        "proposed_title": _trim(payload.get("title"), 200),
        "proposed_object": payload,
        "created_at": _trim(payload.get("created_at") or _utc(), 64),
        "updated_at": _trim(payload.get("updated_at") or _utc(), 64),
    }
    return append_candidate(candidate)


def bootstrap_memory_objects() -> dict[str, Any]:
    harvest_result = harvest_memory_candidates()
    auto_promote_result = auto_promote_candidates(min_confidence=0.9)
    snapshot = _load_json(ACTIVE_SNAPSHOT, {})
    seeds: list[dict[str, Any]] = []
    if isinstance(snapshot, dict):
        workspace = _trim(snapshot.get("authoritative_workspace"), 400)
        startup = _trim(snapshot.get("startup_command"), 240)
        validation = _trim(snapshot.get("required_validation"), 400)
        if workspace:
            seeds.append(
                {
                    "memory_id": "mem_fact_authoritative_workspace_toyos_demo",
                    "memory_type": "fact",
                    "title": "Authoritative workspace for ToyOS execution",
                    "summary": f"{workspace} is the authoritative workspace for ToyOS execution and verification.",
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [workspace],
                        "component": ["execution", "verification"],
                        "task_domain": ["toyos"],
                    },
                    "tags": ["authoritative", "workspace", "toyos"],
                    "authority": "verified",
                    "status": "active",
                    "source_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json"],
                    "evidence_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md"],
                    "validity": {
                        "kind": "revalidate_on_change",
                        "trigger": ["workspace_moved", "snapshot_changed"],
                        "expires_at": None,
                    },
                    "reuse_score": 0.98,
                    "priority": "high",
                    "fact": {
                        "subject": "authoritative_workspace",
                        "statement": f"{workspace} is the authoritative workspace for ToyOS execution and verification.",
                        "source_of_truth": "METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json",
                        "verification_method": "path_exists_and_snapshot_match",
                    },
                }
            )
        if startup:
            seeds.append(
                {
                    "memory_id": "mem_fact_startup_command_metaforge",
                    "memory_type": "fact",
                    "title": "MetaForge startup command",
                    "summary": f"{startup} is the current startup command for refreshing shared dialogue state.",
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [WORKSPACE_ROOT.as_posix()],
                        "component": ["bootstrap", "control"],
                        "task_domain": ["memory", "handoff"],
                    },
                    "tags": ["startup", "bootstrap", "control"],
                    "authority": "verified",
                    "status": "active",
                    "source_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json"],
                    "evidence_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md"],
                    "validity": {
                        "kind": "revalidate_on_change",
                        "trigger": ["startup_command_changed"],
                        "expires_at": None,
                    },
                    "reuse_score": 0.92,
                    "priority": "high",
                    "fact": {
                        "subject": "startup_command",
                        "statement": startup,
                        "source_of_truth": "METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json",
                        "verification_method": "snapshot_match",
                    },
                }
            )
        if validation:
            seeds.append(
                {
                    "memory_id": "mem_decision_validation_first_delivery_claims",
                    "memory_type": "decision",
                    "title": "Delivery claims require explicit validation notes",
                    "summary": validation,
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [WORKSPACE_ROOT.as_posix()],
                        "component": ["delivery", "validation"],
                        "task_domain": ["governance"],
                    },
                    "tags": ["validation", "delivery", "governance"],
                    "authority": "verified",
                    "status": "active",
                    "source_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json"],
                    "evidence_refs": ["METAFORGE_OS_DISPATCH_TEMPLATE.md"],
                    "validity": {
                        "kind": "revalidate_on_change",
                        "trigger": ["policy_changed"],
                        "expires_at": None,
                    },
                    "reuse_score": 0.95,
                    "priority": "high",
                    "decision": {
                        "question": "Can delivery be claimed without validation notes?",
                        "chosen_option": validation,
                        "alternatives_considered": [
                            "Claim delivery on artifact existence alone",
                            "Claim delivery only after explicit validation notes",
                        ],
                        "reasoning": [
                            "Explicit validation is required before claiming delivery.",
                        ],
                        "impact_scope": ["delivery", "handoff", "verification"],
                        "rollback_condition": [
                            "If the control policy is revised to allow unvalidated delivery claims.",
                        ],
                    },
                }
            )
    if startup and snapshot.get("authoritative_workspace"):
        active_expires_at = _future_iso_timestamp(snapshot.get("updated_at"), hours=72)
        seeds.append(
            {
                "memory_id": "mem_handoff_active_runtime_metaforge",
                    "memory_type": "handoff",
                    "title": "Current active runtime handoff",
                    "summary": _trim(snapshot.get("next_action"), 240),
                    "scope": {
                        "system": ["metaforge"],
                        "workspace": [WORKSPACE_ROOT.as_posix()],
                        "component": ["handoff", "runtime"],
                        "task_domain": ["continuity"],
                    },
                    "tags": ["handoff", "continuity", "runtime"],
                    "authority": "verified",
                    "status": "active",
                    "source_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json"],
                    "evidence_refs": ["METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md"],
                    "validity": {
                        "kind": "expires_on_timestamp",
                        "trigger": ["handoff_rotated"],
                        "expires_at": active_expires_at,
                    },
                    "reuse_score": 0.9,
                    "priority": "high",
                    "handoff": {
                        "current_objective": _trim(snapshot.get("next_action"), 240),
                        "authoritative_paths": _listify(
                            [snapshot.get("authoritative_workspace"), WORKSPACE_ROOT.as_posix()],
                            limit=4,
                            item_limit=300,
                        ),
                        "active_execution_roots": _listify(snapshot.get("active_execution_roots"), limit=8, item_limit=220),
                        "required_validations": _listify([snapshot.get("required_validation")], limit=4, item_limit=240),
                        "startup_command": startup,
                        "blockers": _listify([snapshot.get("invalid_delivery_risk")], limit=4, item_limit=120),
                        "next_safe_actions": [
                            "Read the active snapshot before planning.",
                            "Keep validation notes attached to any delivery claim.",
                            "Refresh dialogue memory after routing changes.",
                        ],
                        "forbidden_assumptions": [
                            "Do not assume chat state is durable memory.",
                            "Do not assume artifact presence implies validated delivery.",
                        ],
                        "expires_at": active_expires_at,
                    },
                }
            )

    if MEMORY_MODEL.exists():
        seeds.append(
            {
                "memory_id": "mem_procedure_dialogue_sync_metaforge",
                "memory_type": "procedure",
                "title": "Refresh shared dialogue memory after routing changes",
                "summary": "Use the dialogue sync or assetize flow to keep the shared memory ledger current.",
                "scope": {
                    "system": ["metaforge"],
                    "workspace": [WORKSPACE_ROOT.as_posix()],
                    "component": ["dialogue", "memory"],
                    "task_domain": ["sync", "handoff"],
                },
                "tags": ["dialogue", "sync", "snapshot"],
                "authority": "verified",
                "status": "active",
                "source_refs": ["METAFORGE_OS_MEMORY_MODEL.md"],
                "evidence_refs": ["METAFORGE_OS_DIALOGUE_ASSET_MODEL.md"],
                "validity": {
                    "kind": "revalidate_on_change",
                    "trigger": ["memory_model_changed"],
                    "expires_at": None,
                },
                "reuse_score": 0.84,
                "priority": "medium",
                "procedure": {
                    "goal": "Keep shared dialogue memory synchronized before planning.",
                    "preconditions": [
                        "A current dialogue summary or asset exists.",
                        "The workspace path is known.",
                    ],
                    "steps": [
                        "Capture the current dialogue summary and constraints.",
                        "Sync the dialogue into the shared ledger.",
                        "Regenerate the dialogue memory snapshot.",
                        "Read the active handoff from the refreshed snapshot.",
                    ],
                    "expected_outputs": [
                        "dialogue_memory.json",
                        "session_index.json",
                        "active dialogue snapshot",
                    ],
                    "validation_steps": [
                        "Confirm the shared session count increases or remains stable.",
                        "Confirm the active handoff matches the current workspace.",
                    ],
                    "failure_signals": [
                        "Snapshot is stale after routing changes.",
                        "Dialogue memory still points at an older handoff.",
                    ],
                },
            }
        )

    runtime_failure_fix = _extract_runtime_failure_fix_seed()
    if runtime_failure_fix:
        seeds.append(runtime_failure_fix)

    existing_objects = load_verified_objects()
    existing = {item.get("memory_id") for item in existing_objects if isinstance(item, dict)}
    created: list[dict[str, Any]] = []
    for seed in seeds:
        item = normalize_verified_object(seed, existing=existing)
        existing.add(item["memory_id"])
        created.append(item)
    merged = [item for item in existing_objects if item.get("memory_id") not in {seed.get("memory_id") for seed in created}]
    merged.extend(created)
    merged.sort(key=lambda entry: (_parse_dt(entry.get("updated_at")), entry.get("memory_id") or ""), reverse=True)
    _save_jsonl(OBJECTS_PATH, merged)
    return {
        "status": "bootstrapped",
        "store_path": str(OBJECTS_PATH),
        "candidate_store": str(CANDIDATES_PATH),
        "harvest": harvest_result,
        "auto_promote": auto_promote_result,
        "created_count": len(created),
        "object_count": len(merged),
        "objects": [
            {
                "memory_id": item.get("memory_id"),
                "memory_type": item.get("memory_type"),
                "title": item.get("title"),
            }
            for item in created
        ],
    }


def promote_candidate(*, candidate_id: str | None = None, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates = load_candidates()
    if candidate is None:
        candidate = next((item for item in candidates if item.get("candidate_id") == candidate_id), None)
    if not candidate:
        raise ValueError("candidate not found")

    objects = load_verified_objects()
    existing_ids = {item.get("memory_id") for item in objects if isinstance(item, dict)}
    payload = candidate.get("proposed_object") if isinstance(candidate.get("proposed_object"), dict) else candidate
    if isinstance(payload, dict):
        payload = dict(payload)
        if not _trim(payload.get("memory_id"), 160):
            stable_id = _trim(candidate.get("candidate_id"), 160)
            if stable_id:
                payload["memory_id"] = stable_id.replace("cand_", "mem_", 1)
    promoted = normalize_verified_object(payload, existing=existing_ids)
    promoted["authority"] = "verified"
    promoted["status"] = "active"
    promoted["last_verified_at"] = _utc()
    objects = [entry for entry in objects if entry.get("memory_id") != promoted["memory_id"]]
    objects.append(promoted)
    objects.sort(key=lambda entry: (_parse_dt(entry.get("updated_at")), entry.get("memory_id") or ""), reverse=True)
    _save_jsonl(OBJECTS_PATH, objects)
    return {
        "status": "promoted",
        "candidate_id": candidate.get("candidate_id"),
        "memory_id": promoted.get("memory_id"),
        "memory_type": promoted.get("memory_type"),
        "title": promoted.get("title"),
        "store_path": str(OBJECTS_PATH),
    }


def _is_promotable_candidate(candidate: dict[str, Any], *, min_confidence: float | None = None) -> bool:
    if not isinstance(candidate, dict):
        return False
    proposed = candidate.get("proposed_object") if isinstance(candidate.get("proposed_object"), dict) else {}
    memory_type = _trim(candidate.get("proposed_memory_type") or proposed.get("memory_type"), 32)
    if memory_type not in MEMORY_TYPES:
        return False
    if str(candidate.get("review_status") or "").lower() not in {"pending", "approved"}:
        return False
    if str(candidate.get("authority") or "").lower() not in {"derived", "unverified"}:
        return False
    if candidate.get("conflicts_with"):
        return False
    try:
        confidence = float(candidate.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    threshold = PROMOTION_THRESHOLD_BY_TYPE.get(memory_type, 0.95)
    if min_confidence is not None:
        threshold = max(threshold, float(min_confidence))
    return confidence >= threshold


def auto_promote_candidates(*, min_confidence: float | None = None, limit: int | None = None) -> dict[str, Any]:
    candidates = load_candidates()
    promoted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    promoted_count = 0
    for candidate in candidates:
        if limit is not None and promoted_count >= max(0, int(limit)):
            break
        if not _is_promotable_candidate(candidate, min_confidence=min_confidence):
            skipped.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "memory_id": candidate.get("memory_id") or (candidate.get("proposed_object") or {}).get("memory_id"),
                    "reason": "below_threshold_or_not_promotable",
                }
            )
            continue
        promoted.append(promote_candidate(candidate=candidate))
        promoted_count += 1
    return {
        "status": "auto_promoted",
        "promoted_count": promoted_count,
        "promoted": promoted,
        "skipped_count": len(skipped),
        "skipped": skipped[:12],
        "store_path": str(OBJECTS_PATH),
        "candidate_store": str(CANDIDATES_PATH),
    }


def status_report() -> dict[str, Any]:
    summary = summarize_memory_objects()
    integrity = memory_integrity_report()
    summary.update(
        {
            "store_path": str(OBJECTS_PATH),
            "candidate_path": str(CANDIDATES_PATH),
            "snapshot_path": str(ACTIVE_SNAPSHOT),
            "integrity": integrity,
        }
    )
    return summary
