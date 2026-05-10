from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any
from uuid import uuid4

from json_store import read_json, read_jsonl_tail, update_json
from local_mind_paths import ROOT
from memory_manager import now_iso


CANDIDATES_PATH = ROOT / "data" / "semantic_candidates.json"
SEMANTIC_PATH = ROOT / "data" / "semantic_memory.json"
EVENT_LOG_PATH = ROOT / "data" / "event_log.jsonl"


def read_candidates() -> dict[str, Any]:
    return read_json(CANDIDATES_PATH, {"candidates": []})


def read_semantic() -> dict[str, Any]:
    return read_json(SEMANTIC_PATH, {"memories": []})


def normalize_content(content: str) -> str:
    return " ".join(content.strip().split())


def semantic_signature(content: str) -> str:
    return hashlib.sha256(normalize_content(content).lower().encode("utf-8")).hexdigest()


def find_event(event_id: str) -> dict[str, Any] | None:
    for event in read_jsonl_tail(EVENT_LOG_PATH, 5000):
        if event.get("event_id") == event_id:
            return event
    return None


def semantic_exists(signature: str) -> bool:
    return any(item.get("signature") == signature for item in read_semantic().get("memories", []))


def add_candidate(
    *,
    content: str,
    source: str,
    source_event_ids: list[str],
    importance: float = 0.75,
    confidence: float = 0.75,
    behavioral_effect: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    content = normalize_content(content)
    if not content:
        return {"status": "rejected", "reason": "empty semantic content"}
    if not source_event_ids:
        return {"status": "rejected", "reason": "semantic candidates require source_event_ids"}
    signature = semantic_signature(content)
    if semantic_exists(signature):
        return {"status": "skipped", "reason": "semantic memory already exists", "signature": signature}
    candidate = {
        "candidate_id": f"sem_cand_{uuid4().hex[:12]}",
        "signature": signature,
        "content": content,
        "source": source,
        "source_event_ids": source_event_ids,
        "importance": importance,
        "confidence": confidence,
        "behavioral_effect": behavioral_effect or [],
        "reason": reason,
        "status": "pending_evidence",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    def updater(data: dict[str, Any]) -> dict[str, Any]:
        for item in data.get("candidates", []):
            if item.get("signature") == signature and item.get("status") in {"pending_evidence", "promoted"}:
                return {"status": "skipped", "reason": "candidate already exists", "candidate": item}
        data.setdefault("candidates", []).append(candidate)
        return {"status": "candidate_created", "candidate": candidate}

    return update_json(CANDIDATES_PATH, {"candidates": []}, updater)


def candidate_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    events = []
    missing = []
    unverified = []
    for event_id in candidate.get("source_event_ids", []):
        event = find_event(event_id)
        if event is None:
            missing.append(event_id)
            continue
        events.append(event)
        if not event.get("verified", False):
            unverified.append(event_id)
    return {"events": events, "missing": missing, "unverified": unverified}


def promote_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate_evidence(candidate)
    if evidence["missing"]:
        return {"status": "blocked", "reason": "missing source events", "missing": evidence["missing"]}
    if evidence["unverified"]:
        return {"status": "blocked", "reason": "unverified source events", "unverified": evidence["unverified"]}
    signature = candidate["signature"]
    if semantic_exists(signature):
        return {"status": "skipped", "reason": "semantic memory already exists", "signature": signature}
    memory = {
        "memory_id": f"sem_{uuid4().hex[:12]}",
        "signature": signature,
        "content": candidate["content"],
        "source_events": candidate.get("source_event_ids", []),
        "confidence": candidate.get("confidence", 0.75),
        "importance": candidate.get("importance", 0.75),
        "last_verified_at": now_iso(),
        "behavioral_effect": candidate.get("behavioral_effect", []),
    }

    def updater(data: dict[str, Any]) -> dict[str, Any]:
        for item in data.get("memories", []):
            if item.get("signature") == signature:
                return {"status": "skipped", "reason": "semantic memory already exists", "signature": signature}
        data.setdefault("memories", []).append(memory)
        return {"status": "semantic_promoted", "memory": memory}

    return update_json(SEMANTIC_PATH, {"memories": []}, updater)


def review_candidates() -> dict[str, Any]:
    data = read_candidates()
    results = []
    for candidate in data.get("candidates", []):
        if candidate.get("status") == "promoted":
            continue
        result = promote_candidate(candidate)
        if result.get("status") == "semantic_promoted":
            def mark_promoted(candidate_data: dict[str, Any]) -> dict[str, Any]:
                for item in candidate_data.get("candidates", []):
                    if item.get("candidate_id") == candidate.get("candidate_id"):
                        item["status"] = "promoted"
                        item["promoted_at"] = now_iso()
                        item["memory_id"] = result["memory"]["memory_id"]
                        item["updated_at"] = now_iso()
                        break
                return result

            update_json(CANDIDATES_PATH, {"candidates": []}, mark_promoted)
        results.append({"candidate_id": candidate.get("candidate_id"), "result": result})
    return {"reviewed": len(results), "results": results}


def handle_model_candidates(candidates: list[dict[str, Any]], *, source_ref: str, source_event_ids: list[str]) -> dict[str, Any]:
    results = []
    for candidate in candidates:
        if candidate.get("type") != "semantic":
            continue
        results.append(
            add_candidate(
                content=str(candidate.get("content", "")),
                source=f"model_proposal:{source_ref}",
                source_event_ids=source_event_ids,
                importance=float(candidate.get("importance", 0.75)),
                confidence=float(candidate.get("confidence", 0.75)),
                behavioral_effect=[str(item) for item in candidate.get("behavioral_effect", [])],
                reason=str(candidate.get("reason", "")) if candidate.get("reason") else None,
            )
        )
    review = review_candidates()
    return {
        "processed": len(results),
        "created": sum(1 for item in results if item.get("status") == "candidate_created"),
        "results": results,
        "review": review,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    subparsers.add_parser("review")
    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("content")
    add_parser.add_argument("--event-id", action="append", required=True)
    args = parser.parse_args()

    if args.command == "list":
        print(json.dumps({"candidates": read_candidates()["candidates"], "memories": read_semantic()["memories"]}, indent=2, ensure_ascii=False))
        return
    if args.command == "review":
        print(json.dumps(review_candidates(), indent=2, ensure_ascii=False))
        return
    if args.command == "add":
        result = add_candidate(content=args.content, source="operator_cli", source_event_ids=args.event_id)
        review = review_candidates()
        print(json.dumps({"candidate": result, "review": review}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
