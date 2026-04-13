from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import linkwork_bridge


def test_linkwork_bridge_local_fallback_writes_bridge_log(tmp_path, monkeypatch) -> None:
    job_path = tmp_path / "data" / "executor-logs" / "task.linkwork.job.json"
    job = {
        "task_id": "task_linkwork_local",
        "workspace": str(tmp_path),
        "expected_outputs": ["bundle.md"],
        "handoff_contract": {"output_boundary": ["summary", "generated_files"]},
    }

    monkeypatch.setenv("LINKWORK_JOB_PATH", str(job_path))
    result = linkwork_bridge._run_local(job, job_path=job_path)

    assert result["status"] == "success"
    assert result["dispatch_status"] == "prepared"
    assert result["generated_files"] == ["bundle.md"]
    assert Path(result["bridge_log_path"]).exists()
    assert json.loads(Path(result["bridge_log_path"]).read_text(encoding="utf-8"))["mode"] == "local-fallback"


def test_linkwork_bridge_forwards_and_normalizes_upstream_result(tmp_path, monkeypatch) -> None:
    job_path = tmp_path / "data" / "executor-logs" / "task.linkwork.job.json"
    job = {
        "task_id": "task_linkwork_remote",
        "workspace": str(tmp_path),
        "expected_outputs": ["bundle.md"],
    }

    monkeypatch.setenv("LINKWORK_TARGET_COMMAND", "linkwork-cli")
    monkeypatch.setenv("LINKWORK_TARGET_ARGS", "--stdin-json")
    seen: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        seen["command"] = command
        seen["cwd"] = kwargs.get("cwd")
        seen["input"] = kwargs.get("input")

        class _Result:
            returncode = 0
            stdout = json.dumps(
                {
                    "status": "success",
                    "summary": "Upstream LinkWork completed the handoff.",
                    "generated_files": ["bundle.md"],
                    "evidence_bundle": ["logs/linkwork.log"],
                }
            )
            stderr = ""

        return _Result()

    monkeypatch.setattr("tools.linkwork_bridge.subprocess.run", _fake_run)

    result = linkwork_bridge._run_target(job, job_path=job_path)

    assert seen["command"] == ["linkwork-cli", "--stdin-json"]
    assert seen["cwd"] == str(tmp_path)
    assert json.loads(seen["input"])["task_id"] == "task_linkwork_remote"
    assert result["status"] == "success"
    assert result["dispatch_status"] == "submitted"
    assert result["generated_files"] == ["bundle.md"]
    assert result["evidence_bundle"] == ["logs/linkwork.log"]
    assert result["summary"] == "Upstream LinkWork completed the handoff."
