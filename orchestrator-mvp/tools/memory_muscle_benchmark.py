from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.context_builder import build_context_package
from tools.io_utils import atomic_write_text
from tools.memory_objects import load_candidates, memory_integrity_report, recall_memory_objects

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT.parent
DATA = ROOT / "data"
KNOWLEDGE = WORKSPACE_ROOT / "knowledge"
BENCHMARK_CONFIG = KNOWLEDGE / "memory_muscle_benchmark_v1.json"
BENCHMARK_REPORT = DATA / "memory_muscle_benchmark.json"

REQUIRED_CANDIDATE_FIELDS = {
    "candidate_id",
    "derived_from",
    "confidence",
    "review_status",
    "proposed_memory_type",
    "proposed_title",
    "proposed_object",
}

PROMOTION_THRESHOLD_BY_TYPE = {
    "failure_fix": 0.9,
    "procedure": 0.88,
    "decision": 0.92,
    "fact": 0.94,
    "handoff": 0.96,
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


def _trim(value: Any, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def _candidate_by_id(candidate_id: str) -> dict[str, Any] | None:
    candidate_id = _trim(candidate_id, 160)
    if not candidate_id:
        return None
    for item in load_candidates():
        if _trim(item.get("candidate_id"), 160) == candidate_id:
            return item
    return None


def _candidate_completeness(candidate: dict[str, Any]) -> float:
    present = 0
    for field in REQUIRED_CANDIDATE_FIELDS:
        if candidate.get(field) not in (None, "", [], {}):
            present += 1
    proposed = candidate.get("proposed_object")
    if isinstance(proposed, dict):
        proposed_fields = {
            "memory_type",
            "title",
            "summary",
            "scope",
            "tags",
            "source_refs",
            "evidence_refs",
            "validity",
        }
        present += sum(1 for field in proposed_fields if proposed.get(field) not in (None, "", [], {}))
        total = len(REQUIRED_CANDIDATE_FIELDS) + len(proposed_fields)
    else:
        total = len(REQUIRED_CANDIDATE_FIELDS) + 8
    return present / max(total, 1)


def _is_promotable(candidate: dict[str, Any]) -> bool:
    proposed = candidate.get("proposed_object") if isinstance(candidate.get("proposed_object"), dict) else {}
    memory_type = _trim(candidate.get("proposed_memory_type") or proposed.get("memory_type"), 32)
    if memory_type not in PROMOTION_THRESHOLD_BY_TYPE:
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
    return confidence >= PROMOTION_THRESHOLD_BY_TYPE[memory_type]


def _recall_once(query: str, *, workspace: str | None = None) -> dict[str, Any]:
    payload = recall_memory_objects(query, workspace=workspace, limit=3, include_candidates=True)
    results = payload.get("results", []) if isinstance(payload, dict) else []
    top = results[0] if results else {}
    return {
        "query": query,
        "top_memory_id": top.get("memory_id"),
        "top_title": top.get("title"),
        "top_type": top.get("memory_type"),
        "top_authority": top.get("authority"),
        "top_status": top.get("status"),
        "result_count": len(results),
    }


def _binding_once(request: str, *, workspace: str | None = None) -> dict[str, Any]:
    package = build_context_package(
        prompt=request,
        goal=request,
        repo_path=workspace,
        budget_chars=1600,
        max_modules=5,
    )
    memory_hints = package.get("memory_hints", []) if isinstance(package, dict) else []
    hints = [str(hint) for hint in memory_hints if str(hint).strip()]
    return {
        "request": request,
        "memory_hints": hints[:6],
        "memory_hint_count": len(hints),
    }


def _run_sediment_stage(config: dict[str, Any]) -> dict[str, Any]:
    cases = config.get("sediment_cases") if isinstance(config.get("sediment_cases"), list) else []
    results: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        candidate = _candidate_by_id(case.get("candidate_id", ""))
        if not candidate:
            results.append(
                {
                    "candidate_id": case.get("candidate_id"),
                    "status": "missing",
                    "completeness": 0.0,
                    "promotable": False,
                    "expected_promotable": bool(case.get("expect_promotable")),
                }
            )
            continue
        completeness = _candidate_completeness(candidate)
        promotable = _is_promotable(candidate)
        results.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "memory_id": candidate.get("memory_id"),
                "title": candidate.get("title"),
                "status": "pass" if completeness >= float(case.get("min_completeness") or 0.75) else "attention",
                "completeness": round(completeness, 4),
                "promotable": promotable,
                "expected_promotable": bool(case.get("expect_promotable")),
                "promotable_match": promotable == bool(case.get("expect_promotable")),
            }
        )
    pass_count = sum(1 for item in results if item.get("status") == "pass" and item.get("promotable_match"))
    score = pass_count / len(results) if results else 1.0
    return {
        "status": "pass" if score >= 0.75 else "attention",
        "score": round(score, 4),
        "case_count": len(results),
        "pass_count": pass_count,
        "results": results,
        "rule": "Candidate memory must be structured, scoped, and promotable or rejectable by stable rules.",
    }


def _run_promote_stage(config: dict[str, Any]) -> dict[str, Any]:
    cases = config.get("promote_cases") if isinstance(config.get("promote_cases"), list) else []
    results: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        candidate = _candidate_by_id(case.get("candidate_id", ""))
        if not candidate:
            results.append(
                {
                    "candidate_id": case.get("candidate_id"),
                    "status": "missing",
                    "actual_promotable": False,
                    "expected_promotable": bool(case.get("expect_promotable")),
                }
            )
            continue
        actual_promotable = _is_promotable(candidate)
        completeness = _candidate_completeness(candidate)
        results.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "memory_id": candidate.get("memory_id"),
                "title": candidate.get("title"),
                "status": "pass" if actual_promotable == bool(case.get("expect_promotable")) else "attention",
                "actual_promotable": actual_promotable,
                "expected_promotable": bool(case.get("expect_promotable")),
                "completeness": round(completeness, 4),
            }
        )
    pass_count = sum(1 for item in results if item.get("status") == "pass")
    score = pass_count / len(results) if results else 1.0
    return {
        "status": "pass" if score >= 0.75 else "attention",
        "score": round(score, 4),
        "case_count": len(results),
        "pass_count": pass_count,
        "results": results,
        "rule": "Promotion policy must stay stable: threshold, authority, review state, and conflict checks must agree.",
    }


def _run_recall_stage(config: dict[str, Any], *, workspace: str | None = None) -> dict[str, Any]:
    cases = config.get("recall_cases") if isinstance(config.get("recall_cases"), list) else []
    results: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        query = _trim(case.get("query"), 400)
        expected = _trim(case.get("expected_memory_id"), 160)
        if not query:
            continue
        probe = _recall_once(query, workspace=workspace)
        hit = _trim(probe.get("top_memory_id"), 160) == expected
        results.append(
            {
                "query": query,
                "expected_memory_id": expected,
                "top_memory_id": probe.get("top_memory_id"),
                "top_title": probe.get("top_title"),
                "hit": hit,
            }
        )
    hit_count = sum(1 for item in results if item.get("hit"))
    score = hit_count / len(results) if results else 1.0
    return {
        "status": "pass" if score >= 0.75 else "attention",
        "score": round(score, 4),
        "case_count": len(results),
        "hit_count": hit_count,
        "results": results,
        "rule": "Recall should reproduce the intended memory id for fixed probes.",
    }


def _run_binding_stage(config: dict[str, Any], *, workspace: str | None = None) -> dict[str, Any]:
    cases = config.get("binding_cases") if isinstance(config.get("binding_cases"), list) else []
    results: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        request = _trim(case.get("request"), 300)
        required_titles = [str(item).strip() for item in (case.get("required_titles") or []) if str(item).strip()]
        if not request:
            continue
        probe = _binding_once(request, workspace=workspace)
        hints_text = " ".join(probe.get("memory_hints") or []).lower()
        matches = sum(1 for title in required_titles if title.lower() in hints_text)
        min_matches = int(case.get("min_matches") or len(required_titles) or 1)
        hit = matches >= min_matches
        results.append(
            {
                "request": request,
                "required_titles": required_titles,
                "match_count": matches,
                "min_matches": min_matches,
                "hit": hit,
                "memory_hints": probe.get("memory_hints") or [],
            }
        )
    hit_count = sum(1 for item in results if item.get("hit"))
    score = hit_count / len(results) if results else 1.0
    return {
        "status": "pass" if score >= 0.75 else "attention",
        "score": round(score, 4),
        "case_count": len(results),
        "hit_count": hit_count,
        "results": results,
        "rule": "Memory must appear in the context package used for planning and dispatch.",
    }


def _run_reproduce_stage(config: dict[str, Any], *, workspace: str | None = None) -> dict[str, Any]:
    cases = config.get("reproduce_cases") if isinstance(config.get("reproduce_cases"), list) else []
    results: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        query = _trim(case.get("query"), 400)
        expected = _trim(case.get("expected_memory_id"), 160)
        repeat_count = max(2, int(case.get("repeat_count") or 3))
        if not query:
            continue
        probes = [_recall_once(query, workspace=workspace) for _ in range(repeat_count)]
        top_ids = [_trim(probe.get("top_memory_id"), 160) for probe in probes]
        stable = bool(top_ids) and len(set(top_ids)) == 1 and top_ids[0] == expected
        results.append(
            {
                "query": query,
                "expected_memory_id": expected,
                "top_ids": top_ids,
                "stable": stable,
                "repeat_count": repeat_count,
            }
        )
    stable_count = sum(1 for item in results if item.get("stable"))
    score = stable_count / len(results) if results else 1.0
    return {
        "status": "pass" if score >= 0.75 else "attention",
        "score": round(score, 4),
        "case_count": len(results),
        "stable_count": stable_count,
        "results": results,
        "rule": "Repeated fixed probes should produce the same intended top memory.",
    }


def build_memory_muscle_benchmark(*, workspace: str | None = None) -> dict[str, Any]:
    config = _load_json(BENCHMARK_CONFIG, {})
    if not isinstance(config, dict) or not config:
        config = {
            "sediment_cases": [],
            "promote_cases": [],
            "recall_cases": [],
            "binding_cases": [],
            "reproduce_cases": [],
        }
    else:
        config = config.get("benchmark") if isinstance(config.get("benchmark"), dict) else config
    integrity = memory_integrity_report()
    sediment = _run_sediment_stage(config)
    promote = _run_promote_stage(config)
    recall = _run_recall_stage(config, workspace=workspace or str(ROOT))
    binding = _run_binding_stage(config, workspace=workspace or str(ROOT))
    reproduce = _run_reproduce_stage(config, workspace=workspace or str(ROOT))

    overall_score = round(
        (sediment.get("score", 0.0) * 0.2)
        + (promote.get("score", 0.0) * 0.2)
        + (recall.get("score", 0.0) * 0.25)
        + (binding.get("score", 0.0) * 0.2)
        + (reproduce.get("score", 0.0) * 0.15),
        4,
    )
    status = "pass"
    if overall_score < 0.75:
        status = "attention"
    if overall_score < 0.5:
        status = "degraded"

    report = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "overall_score": overall_score,
        "workspace": workspace or str(ROOT),
        "memory_revision": integrity.get("current_memory_revision"),
        "sediment": sediment,
        "promote": promote,
        "recall": recall,
        "binding": binding,
        "reproduce": reproduce,
        "notes": [
            "This benchmark is fixed to the current memory-muscle contract.",
            "Revalidate after memory-object or context-builder changes.",
        ],
    }
    _atomic_write_json(BENCHMARK_REPORT, report)
    return report


def memory_muscle_benchmark_status(*, workspace: str | None = None, refresh: bool = False) -> dict[str, Any]:
    if refresh or not BENCHMARK_REPORT.exists():
        return build_memory_muscle_benchmark(workspace=workspace)
    payload = _load_json(BENCHMARK_REPORT, {})
    if not payload:
        return build_memory_muscle_benchmark(workspace=workspace)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_memory_muscle_benchmark(), ensure_ascii=False, indent=2))
