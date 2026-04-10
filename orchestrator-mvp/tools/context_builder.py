from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.code_knowledge_graph import build_code_knowledge_graph, query_code_knowledge_graph
from tools.context_cache import get_cached_context, put_cached_context
from tools.dialogue_memory import load_dialogue_memory
from tools.memory_objects import load_candidates, recall_memory_objects
from tools.strategy_engine import load_strategy_memory, select_strategy_hint

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KNOWLEDGE = DATA / "knowledge_base.json"
PROJECT_COMPACTION = DATA / "project_context_compaction.json"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _compress_lines(lines: list[str], max_chars: int) -> str:
    out: list[str] = []
    used = 0
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        add = len(line) + (1 if out else 0)
        if used + add > max_chars:
            break
        out.append(line)
        used += add
    return "\n".join(out)


def _tokenize(text: str) -> list[str]:
    return [token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token]


def _memory_revision() -> str:
    parts: list[str] = []
    for path in [
        ROOT / "tools" / "context_builder.py",
        ROOT / "tools" / "memory_objects.py",
        ROOT / "data" / "memory_objects.jsonl",
        ROOT / "data" / "memory_candidates.jsonl",
    ]:
        if not path.exists():
            parts.append(f"{path.name}:missing")
            continue
        stat = path.stat()
        parts.append(f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}")
    return "|".join(parts)


def _task_type(request: str) -> str:
    text = request.lower()
    if any(token in text for token in ["bug", "debug", "crash", "error", "deadlock", "fix"]):
        return "debugging"
    if any(token in text for token in ["refactor", "rewrite", "restructure"]):
        return "refactor"
    if any(token in text for token in ["design", "architecture", "strategy"]):
        return "design"
    if any(token in text for token in ["test", "verify", "validation", "qemu"]):
        return "verification"
    return "implementation"


def _project_kernel(repo_path: str | None, project: dict[str, Any] | None) -> dict[str, Any]:
    if project:
        payload = {
            "name": project.get("name"),
            "summary": project.get("summary", ""),
            "project_goals": project.get("project_goals", [])[:6],
            "technical_constraints": project.get("technical_constraints", [])[:8],
            "architecture_decisions": project.get("architecture_decisions", [])[:8],
            "working_agreements": project.get("working_agreements", [])[:6],
            "recent_decisions": project.get("recent_decisions", [])[:8],
        }
        if repo_path:
            payload["repo_path"] = repo_path
        return payload
    compaction = _load_json(PROJECT_COMPACTION, {})
    if isinstance(compaction, list):
        kernels = compaction
    elif isinstance(compaction, dict):
        kernels = compaction.get("projects")
    else:
        kernels = None
    if isinstance(kernels, list):
        for item in kernels:
            if repo_path and item.get("repo_path") == repo_path:
                compact = item.get("compact_context", {}) if isinstance(item, dict) else {}
                return {
                    "name": item.get("name"),
                    "summary": item.get("summary", ""),
                    "repo_path": item.get("repo_path"),
                    "project_goals": compact.get("project_goals", []),
                    "technical_constraints": compact.get("technical_constraints", []),
                    "architecture_decisions": compact.get("architecture_decisions", []),
                    "working_agreements": compact.get("working_agreements", []),
                    "recent_decisions": compact.get("recent_decisions", []),
                }
    return {}


def _workspace_matches(repo_path: str | None, workspace: str | None) -> bool:
    repo = str(repo_path or "").strip().lower()
    scope = str(workspace or "").strip().lower()
    if not scope:
        return False
    if not repo:
        return True
    return repo.startswith(scope) or scope.startswith(repo)


def _dialogue_hints(repo_path: str | None) -> dict[str, Any]:
    payload = load_dialogue_memory()
    recent_sessions = payload.get("recent_sessions", []) if isinstance(payload, dict) else []
    relevant = [item for item in recent_sessions if _workspace_matches(repo_path, item.get("workspace"))]
    if not relevant:
        relevant = recent_sessions[:2]
    if not relevant:
        return {"summary_lines": [], "active_handoff": {}}

    active = payload.get("active_handoff", {}) if isinstance(payload, dict) else {}
    lines: list[str] = []
    if active.get("summary"):
        lines.append(f"Active dialogue summary: {active.get('summary')}")
    topics = payload.get("recent_topics", []) if isinstance(payload, dict) else []
    if topics:
        lines.append("Shared dialogue topics: " + ", ".join(topics[:6]))
    constraints = payload.get("shared_constraints", []) if isinstance(payload, dict) else []
    if constraints:
        lines.append("Shared dialogue constraints: " + "; ".join(constraints[:4]))
    decisions = payload.get("recent_decisions", []) if isinstance(payload, dict) else []
    if decisions:
        lines.append("Shared dialogue decisions: " + "; ".join(decisions[:4]))
    for item in relevant[:2]:
        if item.get("summary"):
            lines.append(f"Recent session {item.get('session_id')}: {item.get('summary')}")

    return {
        "summary_lines": lines,
        "active_handoff": active,
        "recent_sessions": relevant[:4],
        "recent_topics": topics[:8],
        "shared_constraints": constraints[:8],
        "recent_decisions": decisions[:8],
    }


def _memory_hints(repo_path: str | None, request: str) -> list[str]:
    payload = recall_memory_objects(
        request,
        workspace=repo_path,
        limit=5,
        include_candidates=True,
    )
    pack = payload.get("memory_pack", {}) if isinstance(payload, dict) else {}
    results = payload.get("results", []) if isinstance(payload, dict) else []
    lines: list[str] = []
    seen: set[str] = set()

    def _add_line(line: str) -> None:
        if line in seen:
            return
        seen.add(line)
        lines.append(line)

    def _label(item: dict[str, Any]) -> str:
        if str(item.get("authority") or "").lower() == "verified" and str(item.get("status") or "").lower() == "active":
            return "Memory"
        return "Memory candidate"

    for item in (pack.get("top_fact") or [])[:2]:
        _add_line(f"{_label(item)} fact: {item.get('title')} :: {item.get('summary')}")
    for item in (pack.get("top_decisions") or [])[:2]:
        _add_line(f"{_label(item)} decision: {item.get('title')} :: {item.get('summary')}")
    for item in (pack.get("top_failure_fixes") or [])[:2]:
        _add_line(f"{_label(item)} failure-fix: {item.get('title')} :: {item.get('summary')}")
    for item in (pack.get("top_procedures") or [])[:2]:
        _add_line(f"{_label(item)} procedure: {item.get('title')} :: {item.get('summary')}")
    active = pack.get("active_handoff") or []
    if active:
        item = active[0]
        _add_line(f"{_label(item)} handoff: {item.get('title')} :: {item.get('summary')}")

    candidate_lines = 0
    for item in results:
        if candidate_lines >= 2:
            break
        if str(item.get("authority") or "").lower() == "verified" and str(item.get("status") or "").lower() == "active":
            continue
        line = f"Memory candidate {item.get('memory_type')}: {item.get('title')} :: {item.get('summary')}"
        if line in seen:
            continue
        _add_line(line)
        candidate_lines += 1

    if candidate_lines < 2:
        tokens = set(_tokenize(request))
        workspace_norm = (repo_path or "").lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in load_candidates():
            title = str(item.get("title") or "").lower()
            summary = str(item.get("summary") or "").lower()
            tags = [str(tag).lower() for tag in (item.get("tags") or [])]
            scope = item.get("scope") or {}
            workspaces = [str(value).lower() for value in (scope.get("workspace") or [])]
            score = 0.0
            for token in tokens:
                if token in title:
                    score += 2.0
                if token in summary:
                    score += 1.5
                if token in tags:
                    score += 0.75
            if workspace_norm and any(workspace_norm in value or value in workspace_norm for value in workspaces):
                score += 1.5
            if str(item.get("status") or "").lower() == "candidate":
                score += 0.25
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], str(pair[1].get("updated_at") or ""), str(pair[1].get("memory_id") or "")), reverse=True)
        for _score, item in scored:
            if candidate_lines >= 2:
                break
            line = f"Memory candidate {item.get('memory_type')}: {item.get('title')} :: {item.get('summary')}"
            if line in seen:
                continue
            _add_line(line)
            candidate_lines += 1
    return lines


def build_context_package(
    *,
    prompt: str,
    goal: str | None,
    repo_path: str | None,
    project: dict[str, Any] | None = None,
    scheduler_hint: dict[str, Any] | None = None,
    max_modules: int = 5,
    budget_chars: int = 3200,
) -> dict[str, Any]:
    strategy_memory = load_strategy_memory()
    strategy_revision = int(strategy_memory.get("revision") or 0)
    memory_revision = _memory_revision()
    cached = get_cached_context(
        prompt=prompt,
        goal=goal,
        repo_path=repo_path,
        max_modules=max_modules,
        budget_chars=budget_chars,
        strategy_revision=strategy_revision,
        memory_revision=memory_revision,
    )
    if cached:
        return cached

    request = (goal or prompt or "").strip()
    task_type = _task_type(request)
    graph_focus = query_code_knowledge_graph(request, limit=max_modules)
    graph = build_code_knowledge_graph()
    module_map = {item.get("module"): item for item in graph.get("modules", [])}

    selected_modules = list(graph_focus.get("module_focus", []))
    expanded: list[str] = []
    for module_name in selected_modules:
        module = module_map.get(module_name) or {}
        for dep in module.get("internal_imports", [])[:2]:
            if dep not in selected_modules and dep not in expanded:
                expanded.append(dep)
            if len(selected_modules) + len(expanded) >= max_modules:
                break
        if len(selected_modules) + len(expanded) >= max_modules:
            break
    dependency_modules = expanded[: max(0, max_modules - len(selected_modules))]

    kernel = _project_kernel(repo_path, project)
    knowledge = _load_json(KNOWLEDGE, {})
    hints = knowledge.get("decision_hints", {}) if isinstance(knowledge, dict) else {}
    repo_learning = knowledge.get("repo_learning", {}) if isinstance(knowledge, dict) else {}
    top_caps = (knowledge.get("capability_reputation", {}) or {}).get("top_capabilities", []) if isinstance(knowledge, dict) else []
    top_workers = (knowledge.get("capability_reputation", {}) or {}).get("top_workers", []) if isinstance(knowledge, dict) else []
    dialogue = _dialogue_hints(repo_path)
    memory_hints = _memory_hints(repo_path, request)
    strategy = select_strategy_hint(
        prompt=prompt,
        goal=goal,
        repo_path=repo_path,
        task_type=task_type,
        memory=strategy_memory,
    )

    plan_lines = [
        f"Task type: {task_type}",
        f"Primary modules: {', '.join(selected_modules) if selected_modules else 'none'}",
        f"Dependency expansion: {', '.join(dependency_modules) if dependency_modules else 'none'}",
        f"Owner teams: {', '.join(graph_focus.get('owner_teams', [])) or 'none'}",
        f"Layers: {', '.join(graph_focus.get('layers', [])) or 'none'}",
    ]
    if scheduler_hint:
        if scheduler_hint.get("owner_teams"):
            plan_lines.append(f"Scheduler owner teams: {', '.join(scheduler_hint.get('owner_teams', [])[:5])}")
        if scheduler_hint.get("layers"):
            plan_lines.append(f"Scheduler layers: {', '.join(scheduler_hint.get('layers', [])[:5])}")
    if strategy.get("applied"):
        plan_lines.append(
            f"Strategy pattern: {strategy.get('pattern_id')} score={strategy.get('pattern_score')}"
        )
    elif strategy.get("explored"):
        plan_lines.append("Strategy mode: exploration path retained this cycle")

    knowledge_lines: list[str] = []
    for item in (knowledge.get("failure_solutions", []) if isinstance(knowledge, dict) else [])[:4]:
        knowledge_lines.append(f"Failure pattern: {item.get('failure')} -> {item.get('solution')}")
    if hints.get("preferred_capabilities"):
        knowledge_lines.append(f"Preferred capabilities: {', '.join(hints.get('preferred_capabilities', [])[:5])}")
    if hints.get("preferred_workers"):
        knowledge_lines.append(f"Preferred workers: {', '.join(hints.get('preferred_workers', [])[:5])}")
    if top_caps:
        knowledge_lines.append("Top capability reputation: " + ", ".join(item.get("capability_id", "") for item in top_caps[:4] if item.get("capability_id")))
    if top_workers:
        knowledge_lines.append("Top worker reputation: " + ", ".join(item.get("worker", "") for item in top_workers[:4] if item.get("worker")))
    if repo_learning:
        knowledge_lines.append(f"Repo learning modules={repo_learning.get('graph_modules', 0)} chunks={repo_learning.get('chunk_count', 0)}")
    if strategy.get("applied"):
        knowledge_lines.extend(strategy.get("hint_lines", [])[:3])
    if memory_hints:
        knowledge_lines.extend(memory_hints[:5])

    project_lines: list[str] = []
    if kernel.get("summary"):
        project_lines.append(f"Project summary: {kernel.get('summary')}")
    for key, label, limit in [
        ("project_goals", "Project goals", 5),
        ("technical_constraints", "Technical constraints", 6),
        ("architecture_decisions", "Architecture decisions", 6),
        ("working_agreements", "Working agreements", 5),
        ("recent_decisions", "Recent decisions", 5),
    ]:
        values = kernel.get(key, []) or []
        for item in values[:limit]:
            project_lines.append(f"{label}: {item}")

    dialogue_lines = dialogue.get("summary_lines", [])

    summary_blocks = [
        _compress_lines(plan_lines, max(400, budget_chars // 4)),
        _compress_lines(project_lines, max(700, budget_chars // 3)),
        _compress_lines(knowledge_lines, max(500, budget_chars // 4)),
        _compress_lines(dialogue_lines, max(500, budget_chars // 4)),
    ]
    if strategy.get("applied") and strategy.get("summary_block"):
        summary_blocks.insert(1, _compress_lines(strategy.get("summary_block", "").splitlines(), max(360, budget_chars // 5)))
    summary_blocks = [block for block in summary_blocks if block]

    payload = {
        "task": request,
        "task_type": task_type,
        "repo_path": repo_path,
        "module_focus": selected_modules,
        "dependency_modules": dependency_modules,
        "owner_teams": graph_focus.get("owner_teams", []),
        "layers": graph_focus.get("layers", []),
        "project_context": kernel,
        "knowledge_hints": {
            "preferred_capabilities": hints.get("preferred_capabilities", []),
            "preferred_workers": hints.get("preferred_workers", []),
            "repo_learning": repo_learning,
        },
        "dialogue_hints": {
            "active_handoff": dialogue.get("active_handoff", {}),
            "recent_topics": dialogue.get("recent_topics", []),
            "shared_constraints": dialogue.get("shared_constraints", []),
            "recent_decisions": dialogue.get("recent_decisions", []),
            "recent_sessions": dialogue.get("recent_sessions", []),
        },
        "memory_hints": memory_hints,
        "strategy": {
            "applied": bool(strategy.get("applied")),
            "explored": bool(strategy.get("explored")),
            "reason": strategy.get("reason"),
            "pattern_id": strategy.get("pattern_id"),
            "pattern_score": strategy.get("pattern_score"),
            "preferred_worker": strategy.get("preferred_worker"),
            "tools_used": strategy.get("tools_used", []),
            "tool_actions": strategy.get("tool_actions", []),
            "structure_summary": strategy.get("structure_summary"),
            "memory_revision": strategy.get("memory_revision", strategy_revision),
            "hint_lines": strategy.get("hint_lines", []),
            "exploration_ratio": strategy.get("exploration_ratio"),
            "candidate_count": strategy.get("candidate_count", 0),
        },
        "verification_scope": {
            "modules": selected_modules + dependency_modules,
            "teams": graph_focus.get("owner_teams", []),
            "layers": graph_focus.get("layers", []),
        },
        "current_plan": plan_lines,
        "summary_blocks": summary_blocks,
        "budget_chars": budget_chars,
    }
    put_cached_context(
        prompt=prompt,
        goal=goal,
        repo_path=repo_path,
        max_modules=max_modules,
        budget_chars=budget_chars,
        context_package=payload,
        strategy_revision=strategy_revision,
        memory_revision=memory_revision,
    )
    return payload
