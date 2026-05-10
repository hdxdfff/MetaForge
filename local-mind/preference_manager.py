from __future__ import annotations

import argparse
import json
from typing import Any
from uuid import uuid4

from json_store import read_json, update_json
from local_mind_paths import ROOT
from memory_manager import now_iso


CANDIDATES_PATH = ROOT / "data" / "preference_candidates.json"
PREFERENCES_PATH = ROOT / "data" / "preference_memory.json"


def read_candidates() -> dict[str, Any]:
    return read_json(CANDIDATES_PATH, {"candidates": []})


def read_preferences() -> dict[str, Any]:
    return read_json(PREFERENCES_PATH, {"preferences": []})


def normalize_content(content: str) -> str:
    return " ".join(content.strip().split())


def preference_exists(content: str) -> bool:
    normalized = normalize_content(content).lower()
    preferences = read_preferences().get("preferences", [])
    return any(normalize_content(item.get("content", "")).lower() == normalized for item in preferences)


def candidate_exists(content: str) -> bool:
    normalized = normalize_content(content).lower()
    candidates = read_candidates().get("candidates", [])
    return any(
        normalize_content(item.get("content", "")).lower() == normalized
        and item.get("status") in {"pending_review", "approved"}
        for item in candidates
    )


def add_candidate(
    *,
    content: str,
    source: str,
    source_ref: str | None = None,
    importance: float = 0.8,
    reason: str | None = None,
) -> dict[str, Any]:
    content = normalize_content(content)
    if not content:
        return {"status": "rejected", "reason": "empty preference content"}
    candidate = {
        "candidate_id": f"pref_cand_{uuid4().hex[:12]}",
        "content": content,
        "source": source,
        "source_ref": source_ref,
        "importance": importance,
        "reason": reason,
        "status": "pending_review",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    def updater(data: dict[str, Any]) -> dict[str, Any]:
        if preference_exists(content):
            return {"status": "skipped", "reason": "preference already confirmed"}
        normalized = normalize_content(content).lower()
        for item in data.get("candidates", []):
            if normalize_content(item.get("content", "")).lower() == normalized and item.get("status") in {"pending_review", "approved"}:
                return {"status": "skipped", "reason": "candidate already pending"}
        data.setdefault("candidates", []).append(candidate)
        return {"status": "candidate_created", "candidate": candidate}

    return update_json(CANDIDATES_PATH, {"candidates": []}, updater)


def commit_preference(
    *,
    content: str,
    source: str,
    source_ref: str | None = None,
    importance: float = 0.8,
    confidence: float = 0.95,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    content = normalize_content(content)
    if not content:
        return {"status": "rejected", "reason": "empty preference content"}
    preference = {
        "preference_id": f"pref_{uuid4().hex[:12]}",
        "memory_id": f"pref_{uuid4().hex[:12]}",
        "content": content,
        "source": source,
        "source_ref": source_ref,
        "candidate_id": candidate_id,
        "importance": importance,
        "confidence": confidence,
        "user_confirmed": True,
        "created_at": now_iso(),
        "last_verified_at": now_iso(),
    }
    def updater(data: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_content(content).lower()
        for item in data.get("preferences", []):
            if normalize_content(item.get("content", "")).lower() == normalized:
                return {"status": "skipped", "reason": "preference already confirmed"}
        data.setdefault("preferences", []).append(preference)
        return {"status": "preference_committed", "preference": preference}

    return update_json(PREFERENCES_PATH, {"preferences": []}, updater)


def approve_candidate(candidate_id: str) -> dict[str, Any]:
    data = read_candidates()
    for candidate in data.get("candidates", []):
        if candidate.get("candidate_id") != candidate_id:
            continue
        if candidate.get("status") == "approved":
            return {"status": "skipped", "reason": "candidate already approved"}
        result = commit_preference(
            content=candidate.get("content", ""),
            source="operator_approval",
            source_ref=candidate_id,
            importance=float(candidate.get("importance", 0.8)),
            candidate_id=candidate_id,
        )
        if result["status"] == "preference_committed":
            def updater(candidate_data: dict[str, Any]) -> dict[str, Any]:
                for item in candidate_data.get("candidates", []):
                    if item.get("candidate_id") == candidate_id:
                        item["status"] = "approved"
                        item["approved_at"] = now_iso()
                        item["updated_at"] = now_iso()
                        break
                return result

            return update_json(CANDIDATES_PATH, {"candidates": []}, updater)
        return result
    return {"status": "not_found", "candidate_id": candidate_id}


def reject_candidate(candidate_id: str, reason: str | None = None) -> dict[str, Any]:
    def updater(data: dict[str, Any]) -> dict[str, Any]:
        for candidate in data.get("candidates", []):
            if candidate.get("candidate_id") == candidate_id:
                candidate["status"] = "rejected"
                candidate["rejected_at"] = now_iso()
                candidate["updated_at"] = now_iso()
                candidate["review_notes"] = reason
                return {"status": "candidate_rejected", "candidate_id": candidate_id}
        return {"status": "not_found", "candidate_id": candidate_id}

    return update_json(CANDIDATES_PATH, {"candidates": []}, updater)


def handle_model_candidates(candidates: list[dict[str, Any]], *, source_ref: str) -> dict[str, Any]:
    results = []
    for candidate in candidates:
        if candidate.get("type") != "preference":
            continue
        results.append(
            add_candidate(
                content=str(candidate.get("content", "")),
                source="model_proposal",
                source_ref=source_ref,
                importance=float(candidate.get("importance", 0.8)),
                reason=str(candidate.get("reason", "")) if candidate.get("reason") else None,
            )
        )
    return {
        "processed": len(results),
        "created": sum(1 for item in results if item.get("status") == "candidate_created"),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list")

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("content")
    add_parser.add_argument("--confirmed", action="store_true")

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("candidate_id")

    reject_parser = subparsers.add_parser("reject")
    reject_parser.add_argument("candidate_id")
    reject_parser.add_argument("--reason", default=None)

    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps({"candidates": read_candidates()["candidates"], "preferences": read_preferences()["preferences"]}, indent=2, ensure_ascii=False))
        return
    if args.command == "add":
        if args.confirmed:
            result = commit_preference(content=args.content, source="operator_cli")
        else:
            result = add_candidate(content=args.content, source="operator_cli")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if args.command == "approve":
        print(json.dumps(approve_candidate(args.candidate_id), indent=2, ensure_ascii=False))
        return
    if args.command == "reject":
        print(json.dumps(reject_candidate(args.candidate_id, args.reason), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
