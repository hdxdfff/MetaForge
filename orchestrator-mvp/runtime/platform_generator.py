from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from runtime.goal_manager import active_goals
from tools.capability_registry import register_capabilities
from tools.platform_registry import register_platform

ROOT = Path(__file__).resolve().parent.parent
FACTORY = ROOT / "factory"
DATA = ROOT / "data"
WORKSPACE = FACTORY / "workspace"
GENERATOR = ROOT / "tools" / "generate_system_workspace.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_global_policy() -> dict:
    policy_path = DATA / 'global_policy_state.json'
    if not policy_path.exists():
        return {}
    try:
        return json.loads(policy_path.read_text(encoding='utf-8-sig'))
    except Exception:
        return {}


def choose_template(goal: dict) -> str:
    target = (goal.get("target") or "").lower()
    policy = _load_global_policy()
    focus = {str(item).strip().lower() for item in policy.get('focus_capabilities', []) if item}
    if any(token in target for token in ["research", "paper", "thesis"]):
        return "research-project"
    if any(token in target for token in ["agent", "assistant", "orchestrator"]):
        return "ai-agent"
    if 'agent_orchestration' in focus and 'webapp_generation' not in focus:
        return "ai-agent"
    if 'webapp_generation' in focus:
        return "webapp"
    if 'research_workflow' in focus or 'experiment_tracking' in focus:
        return "research-project"
    return "webapp"


def generate_platform(goal: dict) -> dict:
    template_id = choose_template(goal)
    project_name = goal.get("target") or goal.get("goal_id") or "platform"
    command = [
        str(ROOT / '..' / 'tools' / 'python311-embed' / 'python.exe'),
        str(GENERATOR),
        template_id,
        project_name,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=ROOT.parent)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or 'platform generation failed')
    payload = json.loads(completed.stdout)
    policy = _load_global_policy()
    platform = {
        "platform_id": f"platform_{uuid4().hex[:10]}",
        "goal_id": goal.get("goal_id"),
        "name": project_name,
        "template_id": template_id,
        "focus_capabilities": policy.get('focus_capabilities', []),
        "workspace": payload.get("workspace") or str(WORKSPACE / payload["project_slug"]),
        "status": "generated",
        "created_at": _utc(),
        "updated_at": _utc(),
        "required_paths": payload.get("required_paths", []),
        "runtime": {
            "status": "generated",
            "health": "unknown",
            "last_run": None,
            "last_checked": _utc(),
            "backend": "workspace",
        },
    }
    platform = register_platform(platform)
    platform["capabilities"] = register_capabilities(platform, extract_capabilities(platform))
    return platform


def generate_pending_platforms() -> list[dict]:
    generated = []
    for goal in active_goals():
        if goal.get("type") not in {"build_platform", "build_product"}:
            continue
        if goal.get("platform_generated"):
            continue
        generated.append(generate_platform(goal))
    return generated


def extract_capabilities(platform: dict) -> list[dict]:
    template_id = platform.get("template_id")
    provider_platform_id = platform.get("platform_id")
    provider_name = platform.get("name")
    base = {
        "provider_platform_id": provider_platform_id,
        "provider_name": provider_name,
        "workspace": platform.get("workspace"),
        "registered_at": _utc(),
        "version": 1,
    }
    if template_id == "research-project":
        return [
            {**base, "capability_id": "research_workflow", "entrypoint": "reports/REPORT.md", "keywords": ["research", "experiment", "paper", "report"]},
            {**base, "capability_id": "experiment_tracking", "entrypoint": "experiments", "keywords": ["experiment", "evaluation", "benchmark"]},
        ]
    if template_id == "ai-agent":
        return [
            {**base, "capability_id": "agent_orchestration", "entrypoint": "orchestration", "keywords": ["agent", "orchestrator", "workflow", "automation"]},
            {**base, "capability_id": "tool_extension", "entrypoint": "tools", "keywords": ["tool", "integration", "plugin", "extension"]},
        ]
    return [
        {**base, "capability_id": "webapp_generation", "entrypoint": "frontend", "keywords": ["web", "frontend", "backend", "site", "app"]},
        {**base, "capability_id": "deploy_scaffold", "entrypoint": "deploy", "keywords": ["deploy", "release", "docker", "service"]},
    ]
