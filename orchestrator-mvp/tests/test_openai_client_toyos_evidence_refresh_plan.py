from __future__ import annotations

from app.openai_client import OpenAIPlanner


def test_toyos_evidence_refresh_avoids_build_loop() -> None:
    planner = OpenAIPlanner()
    prompt = (
        "Refresh the ToyOS evidence chain after the smoke probe ordering fix: confirm "
        "build-report, generic-qemu-smoke-report, and score-report are current, then "
        "emit a concise verification summary tied to the restored ToyOS delivery goal."
    )
    plan = planner.build_plan(prompt=prompt, repo_path=r"D:\codex\generated\toy-os-demo")

    titles = [step.title for step in plan.steps]
    assert "Build Toy OS baseline" not in titles
    assert "Inspect current ToyOS artifacts" in titles
    assert "Emit ToyOS verification summary" in titles
    assert any("toyos-evidence-summary.md" in output for output in plan.steps[-1].outputs)
    assert "without rebuilding" in plan.summary.lower()
