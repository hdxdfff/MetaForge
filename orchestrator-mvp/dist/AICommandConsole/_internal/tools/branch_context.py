from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json
import re

from tools.context_builder import build_context_package
from tools.autonomy_state import autonomy_is_confirmed

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "branch_contexts.json"
PROJECT_COMPACTION = DATA / "project_context_compaction.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"
KNOWLEDGE = DATA / "knowledge_base.json"
CONTROL_LAYER = DATA / "control_layer_status.json"
ENGINEERING_OS = DATA / "engineering_os_status.json"
AUTONOMY = DATA / "autonomy_score.json"
AUTOMATION_LAB = DATA / "automation_lab_status.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _project_rows() -> list[dict[str, Any]]:
    payload = _load_json(PROJECT_COMPACTION, [])
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        project_rows = payload.get("projects")
        if isinstance(project_rows, list):
            rows = project_rows
    rows.append(_meta_factory_project())
    return rows


def _project_kernel(project: dict[str, Any]) -> dict[str, Any]:
    return project.get("compact_context") or project.get("kernel") or {}


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", (text or "").lower()) if token]


def _meta_factory_project() -> dict[str, Any]:
    global_policy = _load_json(GLOBAL_POLICY, {})
    knowledge = _load_json(KNOWLEDGE, {})
    focus_capabilities = global_policy.get("focus_capabilities", []) if isinstance(global_policy, dict) else []
    preferred_workers = ((knowledge.get("decision_hints") or {}).get("preferred_workers", [])) if isinstance(knowledge, dict) else []
    return {
        "project_id": "metafactory-core",
        "name": "Meta Factory Core",
        "repo_path": str(ROOT),
        "summary": "Core AI software engineering operating system, automation lab, routing, scheduler, policy, knowledge, verification, and runtime control workspace.",
        "compact_context": {
            "project_goals": [
                "Maintain and evolve the AI software engineering operating system and automation lab.",
                "Strengthen routing, scheduling, knowledge, verification, and cheap-first execution.",
                "Support branch dialogs that reuse mainline context and factory outputs.",
            ],
            "technical_constraints": [
                "Prefer cheap-first execution and local tools before premium reasoning.",
                "Preserve stable autonomy and verification gates while evolving capabilities.",
                "Treat Codex as control surface and persistent state as the memory source of truth.",
            ],
            "architecture_decisions": [
                "The meta-factory is the mainline system for engineering OS and automation lab work.",
                "Branch work should reuse mainline context packages instead of relying on chat history.",
                "Knowledge, routing, scheduling, policy, and verification changes belong to the meta-factory core.",
            ],
            "working_agreements": [
                "Keep control plane, runtime, and memory layers explicit.",
                "Use structured context packages for branch and change-request work.",
                "Prefer runtime-native repair, verification, and policy-governed evolution.",
            ],
            "recent_decisions": [
                "Global policy, context builder, code graph, and experiment loop are active parts of the mainline system.",
                f"Current focus capabilities: {', '.join(focus_capabilities) if focus_capabilities else 'none recorded'}.",
                f"Preferred workers: {', '.join(preferred_workers) if preferred_workers else 'none recorded'}.",
            ],
        },
    }


def _mainline_state() -> dict[str, Any]:
    control_layer = _load_json(CONTROL_LAYER, {})
    engineering_os = _load_json(ENGINEERING_OS, {})
    autonomy = _load_json(AUTONOMY, {})
    automation_lab = _load_json(AUTOMATION_LAB, {})
    return {
        "control_layer": {
            "status": control_layer.get("status"),
            "quality_score": control_layer.get("quality_score"),
            "patch_gate_status": control_layer.get("patch_gate_status"),
        },
        "engineering_os": {
            "status": engineering_os.get("status"),
            "patch_ready_count": engineering_os.get("patch_ready_count"),
            "verification_status": engineering_os.get("verification_status"),
        },
        "autonomy": {
            "stage": autonomy.get("stage"),
            "score": autonomy.get("score"),
            "stable_autonomy": autonomy_is_confirmed(autonomy),
        },
        "automation_lab": {
            "status": automation_lab.get("status"),
            "maturity_status": ((automation_lab.get("maturity") or {}).get("status")),
            "maturity_score": ((automation_lab.get("maturity") or {}).get("score")),
        },
    }


_DOMAIN_KEYWORDS = {
    "toyos": {"toyos", "kernel", "paging", "syscall", "ring3", "elf", "qemu", "tinyfs", "scheduler"},
    "network": {"network", "packet", "wireshark", "socket", "http", "dns", "tcp", "udp", "routing", "protocol"},
    "database": {"database", "sql", "mysql", "opengauss", "query", "schema", "transaction", "index", "gsql"},
    "frontend": {"frontend", "html", "css", "javascript", "react", "vue", "webapp", "ui"},
    "aimath": {"math", "matrix", "optimization", "probability", "linear", "algebra", "calculus"},
    "metafactory": {"factory", "metafactory", "runtime", "router", "scheduler", "capability", "knowledge", "policy", "verification", "daemon", "toolchain", "branch", "context", "replan", "experiment", "distillation", "autonomy", "engineering", "ownership", "project", "graph"},
}


_PROJECT_DOMAIN_HINTS = {
    "79120c5dbb": "toyos",
    "networklab01": "network",
    "dblab00001": "database",
    "frontend001": "frontend",
    "aimath0001": "aimath",
    "metafactory-core": "metafactory",
}


def _match_project(target: str) -> dict[str, Any] | None:
    tokens = _tokenize(target)
    token_set = set(tokens)
    projects = _project_rows()
    best: dict[str, Any] | None = None
    best_score = -1.0
    for item in projects:
        score = 0.0
        name = str(item.get("name") or "").lower()
        summary = str(item.get("summary") or "").lower()
        repo_path = str(item.get("repo_path") or "").lower()
        kernel = _project_kernel(item)
        domain = _PROJECT_DOMAIN_HINTS.get(str(item.get("project_id") or ""), "")
        domain_keywords = _DOMAIN_KEYWORDS.get(domain, set())
        domain_hits = len(token_set & domain_keywords)
        score += domain_hits * 8
        for token in tokens:
            if token in name:
                score += 4
            if token in summary:
                score += 2
            if token in repo_path:
                score += 1
            for key in ("project_goals", "technical_constraints", "architecture_decisions", "working_agreements", "recent_decisions"):
                for value in kernel.get(key, []) or []:
                    if token in str(value).lower():
                        score += 1
        if domain == "metafactory" and any(token in domain_keywords for token in tokens):
            score += 6
        if project := str(item.get("project_id") or ""):
            if project == "metafactory-core" and any(token in {"knowledge", "policy", "router", "scheduler", "experiment", "context", "replan", "autonomy", "toolchain"} for token in tokens):
                score += 10
        if score > best_score:
            best = item
            best_score = score
    return best if best_score > 0 else _meta_factory_project()


def _load_store() -> dict[str, Any]:
    payload = _load_json(OUT, {})
    if isinstance(payload, dict):
        payload.setdefault("updated_at", _utc())
        payload.setdefault("contexts", {})
        return payload
    return {"updated_at": _utc(), "contexts": {}}


def build_branch_context(
    branch_name: str,
    target: str,
    *,
    department: str | None = None,
    source_session: str | None = None,
    lane_role: str | None = None,
    shares_mainline_context: bool = True,
) -> dict[str, Any]:
    project = _match_project(target)
    repo_path = project.get("repo_path") if project else None
    context_package = build_context_package(
        prompt=target,
        goal=target,
        repo_path=repo_path,
        project=project,
    )
    global_policy = _load_json(GLOBAL_POLICY, {})
    knowledge = _load_json(KNOWLEDGE, {})
    payload = {
        "branch_name": branch_name,
        "target": target,
        "updated_at": _utc(),
        "source_session": source_session,
        "department": department,
        "lane_role": lane_role or "capability_branch",
        "shares_mainline_context": shares_mainline_context,
        "repo_path": repo_path,
        "project": {
            "project_id": project.get("project_id") if project else None,
            "name": project.get("name") if project else None,
            "summary": project.get("summary") if project else None,
            "compact_context": _project_kernel(project or {}),
        },
        "global_policy": {
            "focus_capabilities": global_policy.get("focus_capabilities", []),
            "resource_budget": global_policy.get("resource_budget", {}),
            "experiment_portfolio": global_policy.get("experiment_portfolio", {}),
            "worker_bias_policy": global_policy.get("worker_bias_policy", {}),
        },
        "knowledge_hints": {
            "preferred_capabilities": ((knowledge.get("decision_hints") or {}).get("preferred_capabilities", [])),
            "preferred_workers": ((knowledge.get("decision_hints") or {}).get("preferred_workers", [])),
            "repo_learning": knowledge.get("repo_learning", {}),
        },
        "mainline_state": _mainline_state(),
        "shared_context_refs": {
            "project_context_compaction": str(PROJECT_COMPACTION),
            "global_policy_state": str(GLOBAL_POLICY),
            "knowledge_base": str(KNOWLEDGE),
            "control_layer_status": str(CONTROL_LAYER),
            "engineering_os_status": str(ENGINEERING_OS),
            "autonomy_score": str(AUTONOMY),
            "automation_lab_status": str(AUTOMATION_LAB),
        },
        "context_package": context_package,
    }
    store = _load_store()
    store["updated_at"] = _utc()
    store["contexts"][branch_name] = payload
    _save_json(OUT, store)
    return payload


def get_branch_context(branch_name: str) -> dict[str, Any]:
    store = _load_store()
    return store.get("contexts", {}).get(branch_name, {})


def list_branch_contexts() -> dict[str, Any]:
    store = _load_store()
    contexts = store.get("contexts", {})
    summaries: dict[str, Any] = {}
    for branch_name, payload in contexts.items():
        project = payload.get("project") or {}
        policy = payload.get("global_policy") or {}
        state = payload.get("mainline_state") or {}
        summaries[branch_name] = {
            "target": payload.get("target"),
            "department": payload.get("department"),
            "lane_role": payload.get("lane_role"),
            "shares_mainline_context": payload.get("shares_mainline_context", True),
            "project": project.get("name"),
            "focus_capabilities": policy.get("focus_capabilities", [])[:4],
            "autonomy_stage": ((state.get("autonomy") or {}).get("stage")),
            "control_layer_status": ((state.get("control_layer") or {}).get("status")),
            "engineering_os_status": ((state.get("engineering_os") or {}).get("status")),
            "automation_lab_status": ((state.get("automation_lab") or {}).get("maturity_status")),
        }
    store["summaries"] = summaries
    return store
