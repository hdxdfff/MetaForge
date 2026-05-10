from __future__ import annotations

import json
import shutil

import procedural_manager as procs
from local_mind_paths import ROOT


def make_decision(index: int) -> dict[str, object]:
    return {
        "decision_id": f"dec_selftest_{index:03d}",
        "task_id": "task_selftest_status",
        "committed_to_state": True,
        "executor_results": [
            {
                "action": {
                    "type": "summarize",
                    "target": "reports/local_mind_status.md",
                    "risk_level": "low",
                    "success_criteria": ["report exists", "report non-empty"],
                },
                "result": {"status": "success", "target": "reports/local_mind_status.md"},
                "verified": {"verified": True, "notes": "selftest"},
            }
        ],
    }


def main() -> int:
    workspace = ROOT / ".tmp" / "procedural-gate-selftest"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    procs.CANDIDATES_PATH = workspace / "procedural_candidates.json"
    procs.PROCEDURES_PATH = workspace / "procedural_memory.json"

    results = [procs.record_successful_decision(make_decision(index)) for index in range(3)]
    candidates = procs.read_candidates()["candidates"]
    procedures = procs.read_procedures()["procedures"]
    checks = {
        "first_created": results[0]["status"] == "candidate_created",
        "second_updated": results[1]["status"] == "candidate_updated",
        "third_updated": results[2]["status"] == "candidate_updated",
        "third_promoted": results[2].get("promotion", {}).get("status") == "procedure_promoted",
        "candidate_promoted": len(candidates) == 1 and candidates[0]["status"] == "promoted",
        "procedure_count": len(procedures) == 1,
        "success_count_three": procedures[0]["verified_success_count"] == 3,
    }
    output = {
        "checks": checks,
        "candidate_count": len(candidates),
        "procedure_count": len(procedures),
        "passed": all(checks.values()),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
