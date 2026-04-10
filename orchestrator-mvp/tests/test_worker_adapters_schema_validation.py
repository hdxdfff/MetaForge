from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.audit_validation import parse_audit_output, validate_audit_output
from app.worker_adapters import WorkerAdapters


def _adapter() -> WorkerAdapters:
    return WorkerAdapters.__new__(WorkerAdapters)


def test_audit_output_schema_accepts_structured_coder_output() -> None:
    task = SimpleNamespace(execution_mode="research", task_type="artifact_audit")
    text = (
        "# artifact_audit Result\n"
        "## target_files\n"
        "1. `D:\\codex\\orchestrator-mvp\\app\\worker_adapters.py`\n"
        "## smallest_gap\n"
        "Missing output schema enforcement.\n"
        "## patch_plan\n"
        "Add a schema guard before completion.\n"
        "## validation_commands\n"
        "python -m py_compile app/worker_adapters.py\n"
        "## residual_risk\n"
        "Residual risk is bounded.\n"
    )
    assert _adapter()._output_satisfies_schema(task, "coder", text) is True


def test_audit_output_schema_rejects_generic_summary() -> None:
    task = SimpleNamespace(execution_mode="research", task_type="artifact_audit")
    text = "Generic summary: the audit looks fine and no further action is needed."
    assert _adapter()._output_satisfies_schema(task, "coder", text) is False


def test_review_output_schema_accepts_structured_reviewer_output() -> None:
    task = SimpleNamespace(execution_mode="research", task_type="artifact_audit")
    text = (
        "# Concrete Review Decision\n"
        "## verdict\n"
        "Pass.\n"
        "## evidence_checked\n"
        "Files inspected.\n"
        "## validation_status\n"
        "L1 checks pass.\n"
        "## regression_risks\n"
        "Low bounded risk.\n"
        "## follow_up_patch\n"
        "Add missing test.\n"
        "## next_action\n"
        "Implement follow-up patch.\n"
    )
    assert _adapter()._output_satisfies_schema(task, "reviewer", text) is True


def test_audit_output_parser_handles_code_fences() -> None:
    text = (
        "# artifact_audit Result\n"
        "## target_files\n"
        "1. `D:\\codex\\orchestrator-mvp\\app\\orchestrator.py`\n"
        "## smallest_gap\n"
        "Need stronger validation.\n"
        "## patch_plan\n"
        "Add a gate.\n"
        "## validation_commands\n"
        "```powershell\n"
        "python -m py_compile app/orchestrator.py\n"
        "```\n"
        "## residual_risk\n"
        "Residual risk is bounded.\n"
    )
    parsed = parse_audit_output(text, worker_name="coder")
    assert parsed.target_files == [r"D:\codex\orchestrator-mvp\app\orchestrator.py"]
    assert parsed.validation_commands == ["python -m py_compile app/orchestrator.py"]
    ok, reason = validate_audit_output(text, worker_name="coder")
    assert ok is True
    assert reason == ""


def test_audit_output_schema_accepts_production_audit_output() -> None:
    task = SimpleNamespace(execution_mode="production", task_type="artifact_audit")
    text = (
        "# artifact_audit Result\n"
        "## target_files\n"
        "- `D:\\codex\\orchestrator-mvp\\app\\audit_validation.py`\n"
        "## smallest_gap\n"
        "Production audit output should also be structured.\n"
        "## patch_plan\n"
        "Keep the same sections and validate them.\n"
        "## validation_commands\n"
        "- `python -m py_compile app/audit_validation.py`\n"
        "## residual_risk\n"
        "Residual risk is bounded.\n"
    )
    assert _adapter()._output_satisfies_schema(task, "coder", text) is True
