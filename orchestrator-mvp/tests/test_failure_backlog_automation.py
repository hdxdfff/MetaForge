from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import failure_backlog_automation as fba
from tools import runtime_maintenance as rm


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_failure_backlog_automation_selects_control_plane_followups(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()

    tasks_path = data / "tasks.json"
    history_path = data / "task_history.json"
    archive_path = data / "task_archive.json"
    templates_path = data / "task_templates.json"
    report_path = data / "task_backlog_automation.json"

    _write_json(
        tasks_path,
        [
            {
                "id": "task-1",
                "status": "failed",
                "goal": "Strengthen agent orchestration capability",
                "title": "Implement module agents.deploy_agent",
                "result": {"error": "Task failed after execution error."},
            }
        ],
    )
    _write_json(
        history_path,
        [
            {
                "id": "task-2",
                "status": "timed_out",
                "goal": "Strengthen agent orchestration capability",
                "title": "Implement module runtime.scheduler",
                "result": {"error": "Task timed out after 120 minutes without progress."},
            }
        ],
    )
    _write_json(archive_path, [])
    _write_json(
        templates_path,
        [
            {
                "id": "throughput-policy-audit",
                "name": "Throughput Policy Audit",
                "prompt": "Audit the throughput blueprint against the current controller code.",
                "goal": "Keep the high-throughput control surface aligned with the running orchestrator.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": True,
            },
            {
                "id": "throughput-dispatch-schema",
                "name": "Throughput Dispatch Schema Delta",
                "prompt": "Define the dispatch schema delta needed for task admission.",
                "goal": "Make dispatch admission explicit and machine-checkable.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": True,
            },
            {
                "id": "software-factory",
                "name": "Software Factory Flow",
                "prompt": "Turn a raw request into a structured delivery flow.",
                "goal": "Use the orchestrator as an AI-managed software delivery pipeline.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": True,
            },
        ],
    )

    monkeypatch.setattr(fba, "DATA", data)
    monkeypatch.setattr(fba, "TASKS_PATH", tasks_path)
    monkeypatch.setattr(fba, "TASK_HISTORY_PATH", history_path)
    monkeypatch.setattr(fba, "TASK_ARCHIVE_PATH", archive_path)
    monkeypatch.setattr(fba, "TASK_TEMPLATES_PATH", templates_path)
    monkeypatch.setattr(fba, "REPORT_PATH", report_path)

    async def _fake_create_tasks(payloads):
        created = []
        for index, payload in enumerate(payloads, start=1):
            created.append(
                {
                    "task_id": f"created-{index}",
                    "template_id": payload.get("scheduler_hint", {}).get("template_id"),
                    "handling_mode": payload.get("scheduler_hint", {}).get("handling_mode"),
                    "cluster_key": payload.get("scheduler_hint", {}).get("cluster_key"),
                    "status": "queued",
                }
            )
        return created

    monkeypatch.setattr(fba, "_create_tasks", _fake_create_tasks)

    report = fba.run_failure_backlog_automation("full")

    assert report["mode"] == "full"
    assert report["created_count"] >= 1
    assert report["cluster_recommendations"][0]["handling_mode"] == "control_plane_stabilization"
    assert report["created_tasks"]
    assert report_path.exists()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["created_count"] == report["created_count"]


def test_failure_backlog_automation_light_mode_skips_dispatch(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()

    tasks_path = data / "tasks.json"
    history_path = data / "task_history.json"
    archive_path = data / "task_archive.json"
    templates_path = data / "task_templates.json"
    report_path = data / "task_backlog_automation.json"

    _write_json(tasks_path, [])
    _write_json(history_path, [])
    _write_json(archive_path, [])
    _write_json(templates_path, [])

    monkeypatch.setattr(fba, "DATA", data)
    monkeypatch.setattr(fba, "TASKS_PATH", tasks_path)
    monkeypatch.setattr(fba, "TASK_HISTORY_PATH", history_path)
    monkeypatch.setattr(fba, "TASK_ARCHIVE_PATH", archive_path)
    monkeypatch.setattr(fba, "TASK_TEMPLATES_PATH", templates_path)
    monkeypatch.setattr(fba, "REPORT_PATH", report_path)

    async def _should_not_run(_payloads):
        raise AssertionError("dispatch should not run in light mode")

    monkeypatch.setattr(fba, "_create_tasks", _should_not_run)

    report = fba.run_failure_backlog_automation("light")

    assert report["mode"] == "light"
    assert report["created_count"] == 0
    assert report["toyos_replenishment"]["status"] == "skipped"
    assert report_path.exists()


def test_failure_backlog_automation_prioritizes_template_families() -> None:
    web_cluster = fba._cluster_recommendation(
        {
            "goal": "Fix webapp generation capability",
            "title": "Repair webapp rendering loop",
        },
        count=12,
    )
    tooling_cluster = fba._cluster_recommendation(
        {
            "goal": "Expand tool extension coverage",
            "title": "Implement tool extension bridge",
        },
        count=11,
    )
    release_cluster = fba._cluster_recommendation(
        {
            "goal": "Ship deployable release artifact bundle",
            "title": "Prepare release artifact bundle",
        },
        count=10,
    )
    toyos_cluster = fba._cluster_recommendation(
        {
            "goal": "Restore ToyOS real artifact delivery",
            "title": "Advance ToyOS delivery recovery",
        },
        count=14,
    )

    assert web_cluster["handling_mode"] == "web_or_document_followup"
    assert web_cluster["template_ids"][0] == "browser-reading"
    assert tooling_cluster["handling_mode"] == "tooling_followup"
    assert tooling_cluster["template_ids"][0] == "auto-debug"
    assert release_cluster["handling_mode"] == "delivery_followup"
    assert release_cluster["template_ids"][0] == "deployment-wrapup"
    assert toyos_cluster["handling_mode"] == "toyos_replenishment"
    assert toyos_cluster["template_ids"][0] == "toyos-mainline"

    payloads = fba._select_payloads(
        templates={
            "browser-reading": {
                "id": "browser-reading",
                "name": "Browser Reading and Login Session",
                "prompt": "Use the local browser bridge to open a webpage.",
                "goal": "Handle public and login-gated webpages through the real local browser before escalating.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": False,
            },
            "auto-debug": {
                "id": "auto-debug",
                "name": "Auto Debug Loop",
                "prompt": "Reproduce the failure locally and propose the smallest safe fix.",
                "goal": "Let cheap workers handle routine debugging first.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": True,
            },
            "deployment-wrapup": {
                "id": "deployment-wrapup",
                "name": "Deployment Wrap-up",
                "prompt": "Prepare a local-first deployment checklist.",
                "goal": "Close deployment gaps without waiting on cloud credentials.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": True,
            },
            "toyos-mainline": {
                "id": "toyos-mainline",
                "name": "ToyOS Mainline Development",
                "prompt": "Use WSL and QEMU as the default loop for ToyOS changes.",
                "goal": "Use the assistant as the primary implementation worker for ToyOS.",
                "recommended_context_mode": "lean",
                "default_allow_resource_scan": True,
                "default_allow_repo_status": True,
            },
        },
        tasks=[],
        cluster_recommendations=[web_cluster, tooling_cluster, release_cluster, toyos_cluster],
        desired_active=2,
        desired_pending=5,
        mode="full",
    )

    assert [payload["scheduler_hint"]["template_id"] for payload in payloads] == [
        "browser-reading",
        "auto-debug",
        "deployment-wrapup",
        "toyos-mainline",
    ]


def test_runtime_maintenance_includes_failure_backlog(monkeypatch) -> None:
    monkeypatch.setattr(rm, "reconcile_terminal_task_snapshots", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_execution_evidence_steps", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_stale_task_heartbeats", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "sync_goal_runtime", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "run_goal_storage_audit", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_goal_tasks", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_disabled_kernel_tasks", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_graph_node_tasks", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "run_smoke_hygiene", lambda mode="auto": {"reconciled_smoke": {}, "archived_smoke_noise": []})
    monkeypatch.setattr(rm, "reconcile_stale_running_tasks", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_stale_planning_tasks", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "reconcile_core_messages", lambda: {"status": "ok"})
    monkeypatch.setattr(rm, "_reconcile_duplicate_active_tasks", lambda tasks: {"completed_duplicate_tasks": 0, "task_ids": []})
    monkeypatch.setattr(rm, "run_failure_backlog_automation", lambda mode="full": {"status": "done", "mode": mode})
    monkeypatch.setattr(rm, "_load_json", lambda path, default: [])

    result = rm.maintain_tasks("light")

    assert result["failure_backlog"]["status"] == "done"
    assert result["failure_backlog"]["mode"] == "light"
