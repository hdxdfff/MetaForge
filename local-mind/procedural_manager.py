from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any
from uuid import uuid4

from json_store import read_json, update_json
from local_mind_paths import ROOT
from memory_manager import now_iso


CANDIDATES_PATH = ROOT / "data" / "procedural_candidates.json"
PROCEDURES_PATH = ROOT / "data" / "procedural_memory.json"
PROMOTION_THRESHOLD = 3


def read_candidates() -> dict[str, Any]:
    return read_json(CANDIDATES_PATH, {"candidates": []})


def read_procedures() -> dict[str, Any]:
    return read_json(PROCEDURES_PATH, {"procedures": []})


def action_signature(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": action.get("type"),
        "target": action.get("target"),
        "risk_level": action.get("risk_level", "low"),
        "success_criteria": action.get("success_criteria", []),
    }


def procedure_signature(actions: list[dict[str, Any]]) -> str:
    payload = json.dumps([action_signature(action) for action in actions], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def procedure_exists(signature: str) -> bool:
    return any(item.get("signature") == signature for item in read_procedures().get("procedures", []))


def candidate_to_procedure(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "procedure_id": f"proc_{uuid4().hex[:12]}",
        "signature": candidate["signature"],
        "name": candidate.get("name") or candidate.get("title") or "Verified local workflow",
        "trigger": candidate.get("trigger") or "similar task and success criteria recur",
        "steps": candidate.get("steps", []),
        "risk": candidate.get("risk", "low"),
        "success_criteria": candidate.get("success_criteria", []),
        "source_decision_ids": candidate.get("source_decision_ids", []),
        "verified_success_count": candidate.get("verified_success_count", 0),
        "created_at": now_iso(),
        "last_verified_at": now_iso(),
    }


def promote_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    signature = candidate["signature"]
    if procedure_exists(signature):
        return {"status": "skipped", "reason": "procedure already exists", "signature": signature}
    procedure = candidate_to_procedure(candidate)

    def updater(data: dict[str, Any]) -> dict[str, Any]:
        for item in data.get("procedures", []):
            if item.get("signature") == signature:
                return {"status": "skipped", "reason": "procedure already exists", "signature": signature}
        data.setdefault("procedures", []).append(procedure)
        return {"status": "procedure_promoted", "procedure": procedure}

    return update_json(PROCEDURES_PATH, {"procedures": []}, updater)


def record_successful_decision(decision: dict[str, Any], *, threshold: int = PROMOTION_THRESHOLD) -> dict[str, Any]:
    if not decision.get("committed_to_state"):
        return {"status": "skipped", "reason": "decision was not verified success"}
    actions = [item.get("action", {}) for item in decision.get("executor_results", [])]
    verified_results = [item for item in decision.get("executor_results", []) if item.get("verified", {}).get("verified")]
    if not actions or len(verified_results) != len(actions):
        return {"status": "skipped", "reason": "not all actions verified"}
    risk_levels = {action.get("risk_level", "low") for action in actions}
    if "high" in risk_levels:
        return {"status": "skipped", "reason": "high risk workflow requires manual procedure review"}
    signature = procedure_signature(actions)
    if procedure_exists(signature):
        return {"status": "skipped", "reason": "procedure already promoted", "signature": signature}

    steps = []
    success_criteria: list[str] = []
    for action in actions:
        steps.append(f"{action.get('type')} {action.get('target')}".strip())
        success_criteria.extend(str(item) for item in action.get("success_criteria", []))

    candidate_patch = {
        "signature": signature,
        "title": f"Procedure candidate from task {decision.get('task_id')}",
        "name": f"Verified workflow for {decision.get('task_id')}",
        "trigger": "same task pattern appears again",
        "steps": steps,
        "risk": "medium" if "medium" in risk_levels else "low",
        "success_criteria": sorted(set(success_criteria)),
    }

    def updater(data: dict[str, Any]) -> dict[str, Any]:
        for candidate in data.get("candidates", []):
            if candidate.get("signature") == signature:
                if decision.get("decision_id") not in candidate.setdefault("source_decision_ids", []):
                    candidate["source_decision_ids"].append(decision.get("decision_id"))
                    candidate["verified_success_count"] = int(candidate.get("verified_success_count", 0)) + 1
                    candidate["updated_at"] = now_iso()
                return {"status": "candidate_updated", "candidate": candidate}
        candidate = {
            "candidate_id": f"proc_cand_{uuid4().hex[:12]}",
            **candidate_patch,
            "status": "pending_evidence",
            "source_decision_ids": [decision.get("decision_id")],
            "verified_success_count": 1,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        data.setdefault("candidates", []).append(candidate)
        return {"status": "candidate_created", "candidate": candidate}

    result = update_json(CANDIDATES_PATH, {"candidates": []}, updater)
    candidate = result.get("candidate")
    if candidate and int(candidate.get("verified_success_count", 0)) >= threshold:
        promotion = promote_candidate(candidate)
        if promotion.get("status") == "procedure_promoted":
            def mark_promoted(data: dict[str, Any]) -> dict[str, Any]:
                for item in data.get("candidates", []):
                    if item.get("signature") == signature:
                        item["status"] = "promoted"
                        item["promoted_at"] = now_iso()
                        item["procedure_id"] = promotion["procedure"]["procedure_id"]
                        item["updated_at"] = now_iso()
                        break
                return promotion

            update_json(CANDIDATES_PATH, {"candidates": []}, mark_promoted)
        result["promotion"] = promotion
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("candidate_id")
    args = parser.parse_args()

    if args.command == "list":
        print(json.dumps({"candidates": read_candidates()["candidates"], "procedures": read_procedures()["procedures"]}, indent=2, ensure_ascii=False))
        return
    if args.command == "promote":
        for candidate in read_candidates().get("candidates", []):
            if candidate.get("candidate_id") == args.candidate_id:
                print(json.dumps(promote_candidate(candidate), indent=2, ensure_ascii=False))
                return
        print(json.dumps({"status": "not_found", "candidate_id": args.candidate_id}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
