from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.executor_adapter import ExecutorManager, ExecutorTaskEnvelope
from app.executor_routing import load_verification_policy, resolve_executor_route


def test_resolve_executor_route_selects_linkwork_for_bundle_tasks() -> None:
    route = resolve_executor_route(
        task_type="handoff_doc_generate",
        verification_level="L1",
        execution_mode="governance",
        preferred_worker="linkwork",
    )

    assert route["selected"] is not None
    assert route["selected"]["executor_id"] == "linkwork_executor"
    assert route["verification_profile"]["level"] == "L1"


def test_opencode_alias_is_the_canonical_surface_executor() -> None:
    route = resolve_executor_route(
        task_type="report_refresh",
        verification_level="L2",
        execution_mode="governance",
        executor_hint={"executor_id": "opencode_executor"},
    )

    assert route["selected"] is not None
    assert route["selected"]["executor_id"] == "opencode_executor"


def test_linkwork_executor_prepares_standard_job_bundle(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("app.executor_adapter.DATA", data)
    monkeypatch.setattr("app.executor_adapter.EXECUTOR_STATE_PATH", data / "executors.json")

    manager = ExecutorManager()
    adapter = manager.get_adapter("linkwork_executor")
    assert adapter is not None

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    task = ExecutorTaskEnvelope(
        task_id="task_linkwork_001",
        task_type="artifact_evidence_packaging",
        goal="Package the evidence bundle for verification.",
        inputs={
            "repo_path": str(repo_path),
            "role": "reporter",
            "skill": "evidence_packaging",
            "expected_outputs": {"required_files": ["evidence_bundle.md"]},
        },
        constraints=["no registry writes"],
        expected_outputs=["evidence_bundle.md"],
        verification_level="L1",
        executor_hint={
            "tool_policy": {
                "allow_external_tools": False,
            }
        },
    )

    result = adapter.run_prompt(task, workspace=repo_path)

    assert result.status == "success"
    assert result.needs_verification is True
    assert result.outputs["dispatch_status"] == "prepared"
    assert result.outputs["generated_files"] == ["evidence_bundle.md"]
    assert result.outputs["job_spec"]["role"] == "reporter"
    assert result.outputs["job_spec"]["skill"] == "evidence_packaging"
    assert result.outputs["job_spec"]["tool_policy"]["allow_external_tools"] is False
    assert result.outputs["job_spec"]["tool_policy"]["allow_registry_writes"] is False

    log_path = Path(result.logs_path)
    assert log_path.exists()
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["dispatch_status"] == "prepared"
    assert payload["job_spec"]["handoff_contract"]["verification_required"] is True


def test_linkwork_executor_uses_remote_command_when_configured(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("app.executor_adapter.DATA", data)
    monkeypatch.setattr("app.executor_adapter.EXECUTOR_STATE_PATH", data / "executors.json")
    monkeypatch.setenv("ORCH_LINKWORK_COMMAND", "linkwork-cli")
    monkeypatch.setenv("ORCH_LINKWORK_ARGS", "--stdin-json")

    seen = {}

    def _fake_run(command, **kwargs):
        seen["command"] = command
        seen["stdin"] = kwargs.get("input")
        seen["cwd"] = kwargs.get("cwd")

        class _Result:
            returncode = 0
            stdout = json.dumps(
                {
                    "status": "success",
                    "summary": "LinkWork executed the handoff.",
                    "generated_files": ["bundle.md"],
                    "evidence_bundle": ["logs/linkwork.log"],
                }
            )
            stderr = ""

        return _Result()

    monkeypatch.setattr("app.executor_adapter.subprocess.run", _fake_run)

    manager = ExecutorManager()
    adapter = manager.get_adapter("linkwork_executor")
    assert adapter is not None

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    task = ExecutorTaskEnvelope(
        task_id="task_linkwork_002",
        task_type="delivery_bundle_prepare",
        goal="Package the delivery bundle.",
        inputs={"repo_path": str(repo_path)},
        expected_outputs=["bundle.md"],
        verification_level="L1",
    )

    result = adapter.run_prompt(task, workspace=repo_path)

    assert seen["command"] == ["linkwork-cli", "--stdin-json"]
    assert seen["cwd"] == str(repo_path)
    assert json.loads(seen["stdin"])["task_id"] == "task_linkwork_002"
    assert result.status == "success"
    assert result.outputs["dispatch_status"] == "submitted"
    assert result.outputs["generated_files"] == ["bundle.md"]
    assert result.outputs["evidence_bundle"] == ["logs/linkwork.log"]
    assert result.summary == "LinkWork executed the handoff."


def test_verification_policy_allows_linkwork_for_l1_and_l2() -> None:
    policy = load_verification_policy()
    l1 = next(item for item in policy["levels"] if item["level"] == "L1")
    l2 = next(item for item in policy["levels"] if item["level"] == "L2")
    l3 = next(item for item in policy["levels"] if item["level"] == "L3")

    assert "opencode_executor" in l1["allowed_executors"]
    assert "opencode_executor" in l2["allowed_executors"]
    assert "opencode_executor" in l3["allowed_executors"]
    assert "linkwork_executor" in l1["allowed_executors"]
    assert "linkwork_executor" in l2["allowed_executors"]
