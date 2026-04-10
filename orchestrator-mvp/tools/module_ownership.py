from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.module_ownership_graph import (
    build_review_policy_graph,
    merge_policy_for_modules,
    reviewer_candidates,
)
from tools.organization_model import build_organization_model
from tools.context_builder import build_context_package

DATA = ROOT / "data"
GRAPH = DATA / "code_knowledge_graph.json"
PATCHES = DATA / "patch_submissions.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_submission(item: dict[str, Any]) -> bool:
    changed = False
    module_focus = list(item.get("module_focus") or [])
    owner_teams = sorted({team for team in (item.get("owner_teams") or []) if team})
    reviewer_teams = reviewer_candidates(module_focus, owner_teams)
    review_index = _review_policy_index()
    merge_policy = merge_policy_for_modules(module_focus, owner_teams)
    required_reviews = max(1, len(reviewer_teams)) if reviewer_teams else 0

    if item.get("owner_teams") != owner_teams:
        item["owner_teams"] = owner_teams
        changed = True
    if item.get("reviewer_teams") != reviewer_teams:
        item["reviewer_teams"] = reviewer_teams
        changed = True
    if item.get("merge_policy") != merge_policy:
        item["merge_policy"] = merge_policy
        changed = True
    team_index = build_organization_model().get("teams") or {}
    desired_assignments = [
        {
            "team": team,
            "department": (team_index.get(team) or {}).get("department"),
            "status": "approved" if item.get("status") in {"approved", "merged"} else "pending",
        }
        for team in reviewer_teams
    ]
    if item.get("review_assignments") != desired_assignments:
        item["review_assignments"] = desired_assignments
        changed = True
    review_policy_summary = [
        review_index.get(module) for module in module_focus if review_index.get(module)
    ]
    if item.get("review_policy_summary") != review_policy_summary:
        item["review_policy_summary"] = review_policy_summary
        changed = True
    if item.get("required_reviews") != required_reviews:
        item["required_reviews"] = required_reviews
        changed = True
    if item.get("reviews_completed") is None:
        item["reviews_completed"] = (
            required_reviews if item.get("status") in {"approved", "merged"} else 0
        )
        changed = True

    if item.get("status") == "proposed" and required_reviews == 0:
        item["status"] = "approved"
        item["resolution"] = (
            item.get("resolution")
            or "Auto-approved by ownership normalization because no reviews are required."
        )
        item["reviews_completed"] = 0
        changed = True

    review_gate = (
        "pass"
        if required_reviews == 0
        or int(item.get("reviews_completed", 0) or 0) >= required_reviews
        or item.get("status") in {"approved", "merged"}
        else "pending"
    )
    if item.get("review_gate") != review_gate:
        item["review_gate"] = review_gate
        changed = True
    if item.get("merge_status") == "merged" and item.get("verification_status") != "pass":
        item["verification_status"] = "pass"
        changed = True
    return changed


def _registry() -> dict[str, Any]:
    data = _load_json(PATCHES, {"submissions": []})
    data.setdefault("submissions", [])
    changed = False
    for item in data["submissions"]:
        if _normalize_submission(item):
            changed = True
    if changed:
        _save_json(PATCHES, data)
    return data


def _module_index() -> dict[str, dict[str, Any]]:
    payload = _load_json(GRAPH, {})
    return {item.get("module"): item for item in payload.get("modules", []) if item.get("module")}


def _review_policy_index() -> dict[str, dict[str, Any]]:
    graph = build_review_policy_graph()
    return {
        item.get("module"): item for item in graph.get("merge_policies", []) if item.get("module")
    }


def ownership_summary(
    module_focus: list[str] | None = None, owner_teams: list[str] | None = None
) -> dict[str, Any]:
    module_focus = module_focus or []
    owner_teams = owner_teams or []
    index = _module_index()
    owners = []
    for module in module_focus:
        item = index.get(module) or {}
        owners.append(
            {
                "module": module,
                "owner_team": item.get("owner_team"),
                "owner": item.get("owner"),
                "layer": item.get("layer"),
            }
        )
    return {
        "module_focus": module_focus,
        "owner_teams": owner_teams,
        "ownership": owners,
    }


def patch_required(executing_team: str | None, owner_teams: list[str] | None) -> bool:
    owner_teams = sorted({item for item in (owner_teams or []) if item})
    if not owner_teams or not executing_team:
        return False
    if len(owner_teams) == 1 and owner_teams[0] == executing_team:
        return False
    return True


def create_patch_submission(
    *,
    task_id: str | None,
    node_id: str | None,
    title: str,
    team: str | None,
    owner_teams: list[str] | None,
    module_focus: list[str] | None,
    reason: str,
    repo_path: str | None = None,
) -> dict[str, Any]:
    registry = _registry()
    submissions = registry["submissions"]
    for item in submissions:
        if (
            item.get("task_id") == task_id
            and item.get("node_id") == node_id
            and item.get("status") in {"open", "proposed", "approved"}
        ):
            return item
    patch_id = f"patch_{len(submissions) + 1:04d}"
    merge_policy = merge_policy_for_modules(module_focus or [], owner_teams or [])
    reviewer_teams = reviewer_candidates(module_focus or [], owner_teams or [])
    review_index = _review_policy_index()
    review_policy_summary = [
        review_index.get(module) for module in (module_focus or []) if review_index.get(module)
    ]
    team_index = build_organization_model().get("teams") or {}
    review_assignments = [
        {
            "team": team,
            "department": (team_index.get(team) or {}).get("department"),
            "status": "pending",
        }
        for team in reviewer_teams
    ]
    context_package = build_context_package(
        prompt=reason,
        goal=title,
        repo_path=repo_path,
        scheduler_hint={
            "owner_teams": sorted({item for item in (owner_teams or []) if item}),
            "module_focus": module_focus or [],
            "layers": [item.get("layer") for item in review_policy_summary if item.get("layer")],
        },
    )

    payload = {
        "patch_id": patch_id,
        "created_at": _utc(),
        "updated_at": _utc(),
        "status": "proposed",
        "task_id": task_id,
        "node_id": node_id,
        "title": title,
        "requesting_team": team,
        "owner_teams": sorted({item for item in (owner_teams or []) if item}),
        "module_focus": module_focus or [],
        "reason": reason,
        "resolution": None,
        "verification_status": "pending",
        "merge_status": "blocked",
        "reviewer_teams": reviewer_teams,
        "review_assignments": review_assignments,
        "merge_policy": merge_policy,
        "review_policy_summary": review_policy_summary,
        "context_package": context_package,
        "required_reviews": max(1, len(reviewer_teams)) if reviewer_teams else 0,
        "reviews_completed": 0,
        "review_gate": "pending",
    }
    submissions.append(payload)
    _save_json(PATCHES, registry)
    return payload


def find_patch_submission(
    *, task_id: str | None = None, node_id: str | None = None, patch_id: str | None = None
) -> dict[str, Any] | None:
    submissions = _registry().get("submissions", [])
    for item in submissions:
        if patch_id and item.get("patch_id") == patch_id:
            return item
        if (
            task_id is not None
            and node_id is not None
            and item.get("task_id") == task_id
            and item.get("node_id") == node_id
        ):
            return item
        if node_id is not None and item.get("node_id") == node_id and task_id is None:
            return item
    return None


def record_patch_artifacts(patch_id: str, *, artifacts: dict[str, Any]) -> dict[str, Any]:
    registry = _registry()
    for item in registry.get("submissions", []):
        if item.get("patch_id") != patch_id:
            continue
        item["artifacts"] = artifacts
        item["updated_at"] = _utc()
        _save_json(PATCHES, registry)
        return item
    raise KeyError(patch_id)


def resolve_patch_submission(
    patch_id: str, *, status: str, resolution: str | None = None
) -> dict[str, Any]:
    registry = _registry()
    for item in registry.get("submissions", []):
        if item.get("patch_id") == patch_id:
            item["status"] = status
            item["updated_at"] = _utc()
            item["resolution"] = resolution
            if status == "merged":
                item["merge_status"] = "merged"
                item["verification_status"] = "pass"
                item["reviews_completed"] = item.get("required_reviews", 0)
                item["review_gate"] = "pass"
                for assignment in item.get("review_assignments", []):
                    assignment["status"] = "approved"
            elif status == "rejected":
                item["merge_status"] = "blocked"
                item["review_gate"] = "closed"
            elif status == "approved":
                item["reviews_completed"] = max(
                    int(item.get("reviews_completed", 0) or 0), item.get("required_reviews", 0)
                )
                item["review_gate"] = "pass"
            _save_json(PATCHES, registry)
            return item
    raise KeyError(patch_id)


def refresh_patch_submissions(
    *, verification_passed: bool, verification_status: str
) -> dict[str, Any]:
    registry = _registry()
    changed = False
    for item in registry.get("submissions", []):
        if item.get("status") != "approved":
            continue
        if _normalize_submission(item):
            changed = True
        desired_verification = "pass" if verification_passed else verification_status
        review_gate_passed = item.get("review_gate") == "pass"
        desired_merge = "ready" if verification_passed and review_gate_passed else "blocked"
        if item.get("verification_status") != desired_verification:
            item["verification_status"] = desired_verification
            changed = True
        if item.get("merge_status") != desired_merge:
            item["merge_status"] = desired_merge
            changed = True
        if changed:
            item["updated_at"] = _utc()
    if changed:
        _save_json(PATCHES, registry)
    return patch_submission_status_summary()


def patch_submission_gate(*, node_id: str | None, task_id: str | None = None) -> dict[str, Any]:
    item = find_patch_submission(task_id=task_id, node_id=node_id)
    if not item:
        return {"requires_patch": False, "approved": True, "status": None, "submission": None}
    status = item.get("status")
    return {
        "requires_patch": True,
        "approved": status == "approved",
        "status": status,
        "submission": item,
    }


def list_patch_submissions(status: str | None = None) -> list[dict[str, Any]]:
    submissions = _registry().get("submissions", [])
    if status:
        return [item for item in submissions if item.get("status") == status]
    return submissions


def patch_review_queue() -> dict[str, Any]:
    submissions = list_patch_submissions()
    proposed = [item for item in submissions if item.get("status") == "proposed"]
    approved = [item for item in submissions if item.get("status") == "approved"]
    ready = [item for item in submissions if item.get("merge_status") == "ready"]
    blocked = [
        item
        for item in submissions
        if item.get("merge_status") == "blocked" and item.get("status") not in {"rejected", "merged"}
    ]
    review_pending = [
        item
        for item in submissions
        if item.get("status") not in {"rejected", "merged"}
        and item.get("review_gate") != "pass"
    ]
    return {
        "proposed_count": len(proposed),
        "approved_count": len(approved),
        "ready_count": len(ready),
        "blocked_count": len(blocked),
        "review_pending_count": len(review_pending),
        "review_graph_modules": len(
            {
                entry.get("module")
                for item in submissions
                for entry in (item.get("review_policy_summary") or [])
                if entry.get("module")
            }
        ),
        "recent": list(reversed(submissions))[:10],
    }


def auto_triage_patch_submissions(
    *, verification_passed: bool, verification_status: str
) -> dict[str, Any]:
    registry = _registry()
    approvals: list[str] = []
    ready: list[str] = []
    changed = False
    for item in registry.get("submissions", []):
        if _normalize_submission(item):
            changed = True
        owner_teams = item.get("owner_teams") or []
        requesting_team = item.get("requesting_team")
        if item.get("status") == "proposed":
            auto_approvable = (
                not owner_teams
                or requesting_team in owner_teams
                or int(item.get("required_reviews", 0) or 0) == 0
            )
            if auto_approvable:
                item["status"] = "approved"
                item["resolution"] = (
                    "Auto-approved by ownership triage for same-team, review-free, or single-team ownership."
                )
                item["updated_at"] = _utc()
                item["reviews_completed"] = item.get("required_reviews", 0)
                item["review_gate"] = "pass"
                for assignment in item.get("review_assignments", []):
                    assignment["status"] = "approved"
                approvals.append(item.get("patch_id"))
                changed = True
        if item.get("status") == "approved":
            desired_verification = "pass" if verification_passed else verification_status
            review_gate_passed = item.get("review_gate") == "pass"
            desired_merge = "ready" if verification_passed and review_gate_passed else "blocked"
            if item.get("verification_status") != desired_verification:
                item["verification_status"] = desired_verification
                changed = True
            if item.get("merge_status") != desired_merge:
                item["merge_status"] = desired_merge
                changed = True
            if desired_merge == "ready":
                ready.append(item.get("patch_id"))
            if changed:
                item["updated_at"] = _utc()
    if changed:
        _save_json(PATCHES, registry)
    return {
        "auto_approved": approvals,
        "ready_for_merge": sorted(set(ready)),
        "summary": patch_review_queue(),
    }


def merge_ready_patch_ids() -> list[str]:
    return [
        item.get("patch_id")
        for item in list_patch_submissions()
        if item.get("merge_status") == "ready" and item.get("status") == "approved"
    ]


def auto_merge_ready_submissions(limit: int = 5) -> dict[str, Any]:
    registry = _registry()
    merged: list[str] = []
    changed = False
    for item in registry.get("submissions", []):
        if len(merged) >= limit:
            break
        if item.get("merge_status") != "ready" or item.get("status") != "approved":
            continue
        item["status"] = "merged"
        item["merge_status"] = "merged"
        item["verification_status"] = "pass"
        item["review_gate"] = "pass"
        item["reviews_completed"] = item.get("required_reviews", 0)
        item["resolution"] = "Auto-merged by runtime after patch gate passed."
        item["updated_at"] = _utc()
        merged.append(item.get("patch_id"))
        changed = True
    if changed:
        _save_json(PATCHES, registry)
    return {
        "merged": merged,
        "merged_count": len(merged),
        "summary": patch_review_queue(),
    }


def patch_submission_status_summary() -> dict[str, Any]:
    submissions = list_patch_submissions()
    open_items = [item for item in submissions if item.get("status") in {"open", "proposed"}]
    ready_items = [item for item in submissions if item.get("merge_status") == "ready"]
    merged_items = [item for item in submissions if item.get("merge_status") == "merged"]
    verified_items = [item for item in submissions if item.get("verification_status") == "pass"]
    review_pending_items = [
        item
        for item in submissions
        if item.get("status") not in {"rejected", "merged"}
        and item.get("review_gate") != "pass"
    ]
    return {
        "submission_count": len(submissions),
        "open_count": len(open_items),
        "verified_count": len(verified_items),
        "ready_count": len(ready_items),
        "merged_count": len(merged_items),
        "review_pending_count": len(review_pending_items),
        "recent": list(reversed(submissions))[:10],
    }


if __name__ == "__main__":
    print(json.dumps(patch_submission_status_summary(), ensure_ascii=False, indent=2))
