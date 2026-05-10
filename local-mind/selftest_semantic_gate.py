from __future__ import annotations

import json
import shutil

import semantic_manager as sem
from json_store import append_jsonl
from local_mind_paths import ROOT


def write_event(event_id: str, *, verified: bool) -> None:
    append_jsonl(
        sem.EVENT_LOG_PATH,
        {
            "event_id": event_id,
            "timestamp": "2026-05-10T10:00:00+08:00",
            "source": "selftest",
            "event_type": "selftest",
            "summary": f"selftest {event_id}",
            "raw_observation": {},
            "importance": 0.8,
            "verified": verified,
            "memory_candidate": True,
        },
    )


def main() -> int:
    workspace = ROOT / ".tmp" / "semantic-gate-selftest"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    sem.CANDIDATES_PATH = workspace / "semantic_candidates.json"
    sem.SEMANTIC_PATH = workspace / "semantic_memory.json"
    sem.EVENT_LOG_PATH = workspace / "event_log.jsonl"

    missing = sem.add_candidate(
        content="Missing event facts must not promote",
        source="selftest",
        source_event_ids=["evt_missing"],
    )
    missing_review = sem.review_candidates()

    write_event("evt_unverified", verified=False)
    unverified = sem.add_candidate(
        content="Unverified event facts must not promote",
        source="selftest",
        source_event_ids=["evt_unverified"],
    )
    unverified_review = sem.review_candidates()

    write_event("evt_verified", verified=True)
    verified = sem.add_candidate(
        content="Verified event facts may promote",
        source="selftest",
        source_event_ids=["evt_verified"],
        behavioral_effect=["use verified fact in future context"],
    )
    verified_review = sem.review_candidates()

    memories = sem.read_semantic()["memories"]
    checks = {
        "missing_candidate_created": missing["status"] == "candidate_created",
        "missing_blocked": missing_review["results"][0]["result"]["status"] == "blocked",
        "unverified_candidate_created": unverified["status"] == "candidate_created",
        "unverified_blocked": any(item["result"].get("reason") == "unverified source events" for item in unverified_review["results"]),
        "verified_candidate_created": verified["status"] == "candidate_created",
        "verified_promoted": any(item["result"].get("status") == "semantic_promoted" for item in verified_review["results"]),
        "one_memory_total": len(memories) == 1,
    }
    output = {"checks": checks, "memory_count": len(memories), "passed": all(checks.values())}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
