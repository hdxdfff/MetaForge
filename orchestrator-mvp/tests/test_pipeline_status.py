from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.pipeline_status as pipeline_status


def test_pipeline_status_exposes_ci_cd_and_release_sections() -> None:
    payload = pipeline_status.build_pipeline_status(write_outputs=False)

    assert payload["contract"]["name"] == "ci_cd_pipeline_status"
    assert payload["contract"]["version"] == "1.0"
    assert payload["contract"]["gate_order"] == ["ci", "cd", "release"]

    assert "ci" in payload
    assert "cd" in payload
    assert "release" in payload
    assert "primary_artifact" in payload
    assert "blocked_reasons" in payload
    assert "control_snapshot" in payload
    assert "evidence" in payload

    assert payload["ci"]["status"] in {"pass", "attention"}
    assert payload["cd"]["status"] in {"pass", "attention"}
    assert payload["release"]["status"] in {"pass", "attention"}

    primary_artifact = payload["primary_artifact"]["artifact"]
    assert "artifact_path" in primary_artifact
    assert "real" in primary_artifact
    assert "issues" in primary_artifact
