from __future__ import annotations

import json
import shutil

import preference_manager as prefs
from local_mind_paths import ROOT


def main() -> int:
    workspace = ROOT / ".tmp" / "preference-gate-selftest"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    prefs.CANDIDATES_PATH = workspace / "preference_candidates.json"
    prefs.PREFERENCES_PATH = workspace / "preference_memory.json"

    candidate_result = prefs.add_candidate(
        content="Prefer evidence-backed status reports",
        source="selftest_model",
        source_ref="dec_selftest",
    )
    before_approval = prefs.read_preferences()
    candidate_id = candidate_result.get("candidate", {}).get("candidate_id")
    approval_result = prefs.approve_candidate(candidate_id)
    duplicate_result = prefs.commit_preference(
        content="Prefer evidence-backed status reports",
        source="selftest_duplicate",
    )
    direct_result = prefs.commit_preference(
        content="Prefer compact final answers",
        source="selftest_operator",
    )
    candidates = prefs.read_candidates()["candidates"]
    preferences = prefs.read_preferences()["preferences"]
    checks = {
        "candidate_created": candidate_result["status"] == "candidate_created",
        "not_committed_before_approval": before_approval["preferences"] == [],
        "approval_committed": approval_result["status"] == "preference_committed",
        "duplicate_skipped": duplicate_result["status"] == "skipped",
        "direct_confirmed_committed": direct_result["status"] == "preference_committed",
        "approved_candidate_marked": candidates[0]["status"] == "approved",
        "two_preferences_total": len(preferences) == 2,
    }
    output = {
        "checks": checks,
        "candidate_count": len(candidates),
        "preference_count": len(preferences),
        "passed": all(checks.values()),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
