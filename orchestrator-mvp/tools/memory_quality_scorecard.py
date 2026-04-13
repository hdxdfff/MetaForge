from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.context_builder import build_context_package
from tools.identity_kernel import identity_kernel_status
from tools.memory_objects import load_candidates, load_verified_objects, memory_integrity_report, recall_memory_objects

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCORECARD_PATH = DATA / "memory_quality_scorecard.json"

REQUIRED_OBJECT_FIELDS = {
    "memory_id",
    "memory_type",
    "title",
    "summary",
    "scope",
    "tags",
    "authority",
    "status",
    "source_refs",
    "evidence_refs",
    "created_at",
    "updated_at",
    "last_verified_at",
    "validity",
    "reuse_score",
    "priority",
    "superseded_by",
    "conflicts_with",
}

REQUIRED_CANDIDATE_FIELDS = {
    "candidate_id",
    "derived_from",
    "confidence",
    "review_status",
    "proposed_memory_type",
    "proposed_title",
    "proposed_object",
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_dt(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _slug_query(title: str, summary: str, memory_type: str) -> str:
    parts: list[str] = []
    if title:
        parts.append(title)
    if summary:
        parts.append(summary)
    if memory_type:
        parts.append(memory_type)
    return " ".join(parts).strip()


def _object_completeness(item: dict[str, Any]) -> float:
    present = sum(1 for field in REQUIRED_OBJECT_FIELDS if item.get(field) not in (None, "", [], {}))
    return present / max(len(REQUIRED_OBJECT_FIELDS), 1)


def _candidate_completeness(item: dict[str, Any]) -> float:
    present = 0
    for field in REQUIRED_CANDIDATE_FIELDS:
        value = item.get(field)
        if value not in (None, "", [], {}):
            present += 1
    proposed = item.get("proposed_object")
    if isinstance(proposed, dict):
        proposed_fields = {"memory_type", "title", "summary", "scope", "tags", "source_refs", "evidence_refs", "validity"}
        present += sum(1 for field in proposed_fields if proposed.get(field) not in (None, "", [], {}))
        total = len(REQUIRED_CANDIDATE_FIELDS) + len(proposed_fields)
    else:
        total = len(REQUIRED_CANDIDATE_FIELDS) + 8
    return present / max(total, 1)


def _top_probe_queries(verified: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for item in verified[:3]:
        probes.append(
            {
                "query": _slug_query(str(item.get("title") or ""), str(item.get("summary") or ""), str(item.get("memory_type") or "")),
                "expected_memory_id": item.get("memory_id"),
                "expected_title": item.get("title"),
                "source": "verified",
            }
        )
    for item in candidates[:2]:
        proposed = item.get("proposed_object") if isinstance(item.get("proposed_object"), dict) else {}
        probes.append(
            {
                "query": _slug_query(str(proposed.get("title") or item.get("title") or ""), str(proposed.get("summary") or item.get("summary") or ""), str(proposed.get("memory_type") or item.get("proposed_memory_type") or item.get("memory_type") or "")),
                "expected_candidate_id": item.get("candidate_id"),
                "expected_title": proposed.get("title") or item.get("title"),
                "source": "candidate",
            }
        )
    return [probe for probe in probes if probe.get("query")]


def _recall_hit_probe(probe: dict[str, Any], *, workspace: str | None = None) -> dict[str, Any]:
    payload = recall_memory_objects(
        probe["query"],
        workspace=workspace,
        limit=3,
        include_candidates=True,
    )
    results = payload.get("results", []) if isinstance(payload, dict) else []
    top = results[0] if results else {}
    top_title = str(top.get("title") or "").lower()
    top_id = str(top.get("memory_id") or "").lower()
    expected_title = str(probe.get("expected_title") or "").lower()
    expected_id = str(probe.get("expected_memory_id") or probe.get("expected_candidate_id") or "").lower()
    query_tokens = [token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in probe["query"]).split() if token]
    token_hit = any(token and (token in top_title or token in top_id) for token in query_tokens[:6])
    exact_hit = bool(expected_id and expected_id == top_id)
    title_hit = bool(expected_title and expected_title in top_title)
    hit = exact_hit or title_hit or token_hit
    return {
        "query": probe["query"],
        "expected": probe.get("expected_memory_id") or probe.get("expected_candidate_id"),
        "source": probe.get("source"),
        "top_result": {
            "memory_id": top.get("memory_id"),
            "memory_type": top.get("memory_type"),
            "title": top.get("title"),
            "authority": top.get("authority"),
            "status": top.get("status"),
        },
        "hit": hit,
    }


def _binding_probe(request: str, *, workspace: str | None = None) -> dict[str, Any]:
    package = build_context_package(
        prompt=request,
        goal=request,
        repo_path=workspace,
        budget_chars=1600,
        max_modules=5,
    )
    memory_hints = package.get("memory_hints", []) if isinstance(package, dict) else []
    normalized_request = "".join(ch.lower() if ch.isalnum() else " " for ch in request)
    tokens = [token for token in normalized_request.split() if token]
    matching_hints = []
    for hint in memory_hints:
        hint_text = str(hint).lower()
        if any(token in hint_text for token in tokens[:8]):
            matching_hints.append(hint)
    return {
        "request": request,
        "memory_hint_count": len(memory_hints),
        "matching_hint_count": len(matching_hints),
        "binding_hit": bool(memory_hints) and bool(matching_hints),
        "memory_hints": memory_hints[:5],
    }


def build_memory_quality_scorecard(*, workspace: str | None = None) -> dict[str, Any]:
    verified = load_verified_objects()
    candidates = load_candidates()
    integrity = memory_integrity_report()
    identity = identity_kernel_status(refresh=False)

    verified_total = len(verified)
    candidate_total = len(candidates)
    verified_completeness = (
        sum(_object_completeness(item) for item in verified) / verified_total if verified_total else 1.0
    )
    candidate_completeness = (
        sum(_candidate_completeness(item) for item in candidates) / candidate_total if candidate_total else 1.0
    )
    duplicate_penalty = 0.15 * (
        len(integrity.get("duplicate_verified_memory_ids") or [])
        + len(integrity.get("duplicate_candidate_ids") or [])
        + len(integrity.get("duplicate_candidate_memory_ids") or [])
    )
    expiry_penalty = 0.2 if (integrity.get("expired_handoffs") or []) else 0.0
    write_quality_score = max(0.0, min(1.0, (verified_completeness * 0.5) + (candidate_completeness * 0.4) + 0.1 - duplicate_penalty - expiry_penalty))

    probe_queries = _top_probe_queries(verified, candidates)
    recall_probes = [_recall_hit_probe(probe, workspace=workspace or str(ROOT)) for probe in probe_queries]
    recall_hit_rate = (
        sum(1 for probe in recall_probes if probe.get("hit")) / len(recall_probes) if recall_probes else 1.0
    )

    binding_requests = [
        "Fix ToyOS build readiness and validation",
        "Investigate state persistence continuity drift",
        "Refresh shared dialogue memory and handoff",
    ]
    binding_probes = [_binding_probe(request, workspace=workspace or str(ROOT)) for request in binding_requests]
    binding_hit_rate = (
        sum(1 for probe in binding_probes if probe.get("binding_hit")) / len(binding_probes) if binding_probes else 1.0
    )

    consistency_findings = identity.get("consistency", {}).get("finding_count", 0) if isinstance(identity, dict) else 0
    memory_status = str((integrity or {}).get("status") or "").lower()
    identity_status = str((identity or {}).get("status") or "").lower()
    runtime_health = str(((identity or {}).get("runtime") or {}).get("health") or "").lower()
    authority_active = bool(((identity or {}).get("authority") or {}).get("session_active"))
    expired_handoff_count = len(integrity.get("expired_handoffs") or [])
    duplicate_count = (
        len(integrity.get("duplicate_verified_memory_ids") or [])
        + len(integrity.get("duplicate_candidate_ids") or [])
        + len(integrity.get("duplicate_candidate_memory_ids") or [])
    )
    anti_drift_score = max(
        0.0,
        min(
            1.0,
            1.0
            - (0.2 if memory_status != "ok" else 0.0)
            - (0.2 if not authority_active else 0.0)
            - (0.2 if runtime_health != "healthy" else 0.0)
            - (0.15 if expired_handoff_count > 0 else 0.0)
            - (0.15 if duplicate_count > 0 else 0.0)
            - (0.1 if (integrity.get("stale_cache_entry_count") or 0) > 0 else 0.0),
        ),
    )

    overall_score = round(
        (write_quality_score * 0.3)
        + (recall_hit_rate * 0.25)
        + (binding_hit_rate * 0.25)
        + (anti_drift_score * 0.2),
        4,
    )
    status = "pass"
    if overall_score < 0.65 or anti_drift_score < 0.7:
        status = "attention"
    if overall_score < 0.45:
        status = "degraded"

    report = {
        "updated_at": identity.get("updated_at") if isinstance(identity, dict) else None,
        "status": status,
        "overall_score": overall_score,
        "workspace": workspace or str(ROOT),
        "memory_integrity_snapshot": {
            "current_memory_revision": integrity.get("current_memory_revision"),
            "expired_handoff_count": expired_handoff_count,
            "stale_cache_entry_count": integrity.get("stale_cache_entry_count") or 0,
        },
        "write_quality": {
            "status": "pass" if write_quality_score >= 0.8 else "attention",
            "score": round(write_quality_score, 4),
            "verified_object_count": verified_total,
            "candidate_count": candidate_total,
            "verified_completeness": round(verified_completeness, 4),
            "candidate_completeness": round(candidate_completeness, 4),
            "duplicate_verified_memory_ids": integrity.get("duplicate_verified_memory_ids") or [],
            "duplicate_candidate_ids": integrity.get("duplicate_candidate_ids") or [],
            "duplicate_candidate_memory_ids": integrity.get("duplicate_candidate_memory_ids") or [],
            "expired_handoffs": integrity.get("expired_handoffs") or [],
            "rule": "candidate entries must be structured, scoped, evidence-backed, and conflict-free before promotion.",
        },
        "recall_hit_rate": {
            "status": "pass" if recall_hit_rate >= 0.75 else "attention",
            "score": round(recall_hit_rate, 4),
            "probe_count": len(recall_probes),
            "hit_count": sum(1 for probe in recall_probes if probe.get("hit")),
            "probes": recall_probes,
            "rule": "top recall should surface the intended memory or a close title/token match in the first few results.",
        },
        "behavior_binding": {
            "status": "pass" if binding_hit_rate >= 0.67 else "attention",
            "score": round(binding_hit_rate, 4),
            "probe_count": len(binding_probes),
            "hit_count": sum(1 for probe in binding_probes if probe.get("binding_hit")),
            "probes": binding_probes,
            "rule": "memory should appear inside context packages used for planning and dispatch, not only in archives.",
        },
        "anti_drift": {
            "status": "pass" if anti_drift_score >= 0.8 else "attention",
            "score": round(anti_drift_score, 4),
            "identity_status": identity_status,
            "memory_status": memory_status,
            "runtime_health": runtime_health,
            "consistency_finding_count": consistency_findings,
            "stale_cache_entry_count": integrity.get("stale_cache_entry_count") or 0,
            "rule": "identity, authority, and continuity should remain self-consistent across long runs.",
        },
        "notes": [
            "This scorecard is a live operational probe, not a substitute for soak evidence.",
            "Recall probes are derived from current memory contents and context injection paths.",
        ],
    }
    _atomic_write_json(SCORECARD_PATH, report)
    return report


def _scorecard_needs_refresh(payload: dict[str, Any], *, workspace: str | None = None) -> bool:
    if not payload:
        return True
    if (payload.get("workspace") or str(ROOT)) != (workspace or str(ROOT)):
        return True

    integrity = memory_integrity_report()
    snapshot = payload.get("memory_integrity_snapshot") if isinstance(payload.get("memory_integrity_snapshot"), dict) else {}
    cached_expired = payload.get("write_quality", {}).get("expired_handoffs") if isinstance(payload.get("write_quality"), dict) else []
    current_expired = integrity.get("expired_handoffs") or []

    if snapshot.get("current_memory_revision") != integrity.get("current_memory_revision"):
        return True
    if int(snapshot.get("expired_handoff_count") or 0) != len(current_expired):
        return True
    if int(snapshot.get("stale_cache_entry_count") or 0) != int(integrity.get("stale_cache_entry_count") or 0):
        return True
    if cached_expired != current_expired:
        return True

    updated_at = _parse_dt(payload.get("updated_at"))
    if updated_at == datetime.min.replace(tzinfo=timezone.utc):
        return True
    for handoff in current_expired:
        if _parse_dt(handoff.get("expires_at")) > updated_at:
            return True
    return False


def memory_quality_scorecard_status(*, workspace: str | None = None, refresh: bool = False) -> dict[str, Any]:
    if refresh or not SCORECARD_PATH.exists():
        return build_memory_quality_scorecard(workspace=workspace)
    payload = _load_json(SCORECARD_PATH, {})
    if not payload:
        return build_memory_quality_scorecard(workspace=workspace)
    if _scorecard_needs_refresh(payload, workspace=workspace):
        return build_memory_quality_scorecard(workspace=workspace)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_memory_quality_scorecard(), ensure_ascii=False, indent=2))
