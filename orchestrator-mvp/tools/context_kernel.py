from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.dialogue_memory import load_dialogue_memory, rebuild_dialogue_memory
from tools.io_utils import atomic_write_json, atomic_write_text
from tools.task_state_tools import completed_goal_task_ids, reconcile_core_messages

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_error(text: str) -> str:
    lowered = (text or "").lower()
    if "invalid_api_key" in lowered or "incorrect api key" in lowered:
        return "invalid_api_key"
    if "approval mode is manual" in lowered:
        return "manual_approval_gate"
    if "module not found" in lowered or "cannot find module" in lowered:
        return "missing_module"
    if "timeout" in lowered:
        return "timeout"
    if "connection" in lowered or "remote server" in lowered:
        return "connectivity"
    return (text or "unknown_failure").strip()[:120]


def _compact_list(items: list[Any], limit: int = 5) -> list[Any]:
    cleaned = []
    seen = set()
    for item in items or []:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _project_risks(
    project: dict[str, Any],
    failure_patterns: list[dict[str, Any]],
    active_tasks: list[dict[str, Any]],
    failed_tasks: list[dict[str, Any]],
) -> list[str]:
    repo_path = str(project.get("repo_path") or "")
    risks: list[str] = []
    repo_active = [task for task in active_tasks if str(task.get("repo_path") or "") == repo_path]
    repo_failed = [task for task in failed_tasks if str(task.get("repo_path") or "") == repo_path]
    if repo_failed:
        risks.append(f"{len(repo_failed)} recent failed tasks in this workspace")
    if len(repo_active) >= 4:
        risks.append(f"{len(repo_active)} active tasks may indicate coordination pressure")
    for pattern in failure_patterns[:4]:
        if pattern.get("count", 0) >= 2:
            risks.append(f"Repeated failure pattern: {pattern.get('pattern')}")
    return _compact_list(risks, limit=4)


def rebuild() -> dict[str, Any]:
    reconcile_core_messages()
    tasks = _load_json(DATA / 'tasks.json', [])
    projects = _load_json(DATA / 'projects.json', [])
    core_messages = _load_json(DATA / 'core_messages.json', [])
    releases = _load_json(DATA / 'release_records.json', [])
    policy = _load_json(DATA / 'policy.json', {})
    control = _load_json(DATA / 'control_center_state.json', {"paused": False, "status": "active"})
    resident = _load_json(DATA / 'core_agent_profile.json', {})
    completed_task_ids = completed_goal_task_ids()
    dialogue_memory = load_dialogue_memory() or rebuild_dialogue_memory()

    if not resident:
        resident = {
            "name": "Resident Core Agent",
            "mode": "codex-first",
            "role": "Supervise local cheap-first automation, intervene only on escalations, architecture conflicts, risky actions, or repeated failures.",
            "expensive_model_policy": "Keep premium reasoning for contradictions, structural decisions, security boundaries, and repeated failed debug loops.",
            "updated_at": _utc(),
        }
        atomic_write_json(DATA / 'core_agent_profile.json', resident)

    open_escalations = [item for item in core_messages if item.get('status', 'open') == 'open']
    failed_tasks = [task for task in tasks if task.get('status') == 'failed']
    active_tasks = [
        task for task in tasks
        if task.get('status') in {'planning', 'running', 'verification_pending', 'verification_running'} and task.get('id') not in completed_task_ids
    ]

    project_summaries = []
    project_context_kernels = []
    project_context_compaction = []
    for project in projects:
        project_summaries.append({
            "id": project.get('id'),
            "name": project.get('name'),
            "repo_path": project.get('repo_path'),
            "summary": project.get('summary', ''),
            "project_goals": project.get('project_goals', [])[:6],
            "technical_constraints": project.get('technical_constraints', [])[:6],
            "architecture_decisions": project.get('architecture_decisions', [])[:8],
            "architecture_notes": project.get('architecture_notes', [])[:6],
            "working_agreements": project.get('working_agreements', [])[:6],
            "recent_decisions": project.get('recent_decisions', [])[:8],
            "preferred_context_mode": project.get('preferred_context_mode', 'lean'),
        })
        project_context_kernels.append({
            "project_id": project.get('id'),
            "name": project.get('name'),
            "repo_path": project.get('repo_path'),
            "summary": project.get('summary', ''),
            "kernel": {
                "project_goals": project.get('project_goals', [])[:8],
                "technical_constraints": project.get('technical_constraints', [])[:8],
                "architecture_decisions": project.get('architecture_decisions', [])[:10],
                "architecture_notes": project.get('architecture_notes', [])[:8],
                "working_agreements": project.get('working_agreements', [])[:8],
                "recent_decisions": project.get('recent_decisions', [])[:10],
            },
        })
        project_context_compaction.append({
            "project_id": project.get("id"),
            "name": project.get("name"),
            "repo_path": project.get("repo_path"),
            "summary": str(project.get("summary", "")).strip()[:240],
            "compact_context": {
                "project_goals": _compact_list(project.get("project_goals", []), limit=4),
                "technical_constraints": _compact_list(project.get("technical_constraints", []), limit=5),
                "architecture_decisions": _compact_list(project.get("architecture_decisions", []), limit=5),
                "architecture_notes": _compact_list(project.get("architecture_notes", []), limit=4),
                "working_agreements": _compact_list(project.get("working_agreements", []), limit=4),
                "recent_decisions": _compact_list(project.get("recent_decisions", []), limit=6),
                "active_risks": [],
            },
        })

    decision_log = []
    for project in projects:
        for item in project.get('recent_decisions', [])[:8]:
            decision_log.append({
                "source": "project_memory",
                "project": project.get('name'),
                "decision": item,
            })
    for release in releases[-10:]:
        if release.get('notes'):
            decision_log.append({
                "source": "release_record",
                "project": release.get('repo_path') or release.get('repo_id'),
                "decision": release.get('notes'),
            })

    counter = Counter()
    examples: dict[str, str] = {}
    for task in failed_tasks:
        err = task.get('result', {}).get('error') or '\n'.join(event.get('message', '') for event in task.get('events', []) if event.get('level') == 'error')
        key = _normalize_error(err)
        counter[key] += 1
        examples.setdefault(key, err[:240])
    for message in open_escalations:
        key = _normalize_error(message.get('body', '') or message.get('title', ''))
        counter[key] += 1
        examples.setdefault(key, (message.get('body') or message.get('title') or '')[:240])

    failure_patterns = [
        {"pattern": key, "count": count, "example": examples.get(key, '')}
        for key, count in counter.most_common(12)
    ]

    for item in project_context_compaction:
        project = next((entry for entry in projects if entry.get('id') == item.get('project_id')), {})
        item["compact_context"]["active_risks"] = _project_risks(
            project,
            failure_patterns=failure_patterns,
            active_tasks=active_tasks,
            failed_tasks=failed_tasks,
        )

    escalation_inbox = []
    for item in open_escalations[:20]:
        escalation_inbox.append({
            "id": item.get('id'),
            "severity": item.get('severity', 'info'),
            "title": item.get('title', 'Untitled escalation'),
            "task_id": item.get('task_id'),
            "repo_path": item.get('repo_path'),
            "created_at": item.get('created_at'),
            "status": item.get('status', 'open'),
            "body": item.get('body', '')[:400],
        })

    shared_dialogue = {
        "updated_at": dialogue_memory.get("updated_at"),
        "session_count": dialogue_memory.get("session_count", 0),
        "message_count": dialogue_memory.get("message_count", 0),
        "recent_topics": dialogue_memory.get("recent_topics", [])[:6],
        "recent_decisions": dialogue_memory.get("recent_decisions", [])[:6],
        "shared_constraints": dialogue_memory.get("shared_constraints", [])[:6],
        "active_handoff": dialogue_memory.get("active_handoff", {}),
    }

    hot_context = {
        "updated_at": _utc(),
        "control_center": control,
        "policy_version": policy.get('version'),
        "active_task_count": len(active_tasks),
        "failed_task_count": len(failed_tasks),
        "open_escalation_count": len(open_escalations),
        "active_tasks": [
            {
                "id": task.get('id'),
                "status": task.get('status'),
                "goal": task.get('goal'),
                "repo_path": task.get('repo_path'),
                "updated_at": task.get('updated_at'),
            }
            for task in active_tasks[:8]
        ],
        "failed_tasks": [
            {
                "id": task.get('id'),
                "status": task.get('status'),
                "goal": task.get('goal'),
                "repo_path": task.get('repo_path'),
                "error": (task.get('result', {}) or {}).get('error'),
                "updated_at": task.get('updated_at'),
            }
            for task in failed_tasks[:8]
        ],
        "shared_dialogue": shared_dialogue,
    }

    context_kernel = {
        "updated_at": _utc(),
        "resident_core_agent": resident,
        "hot_context": hot_context,
        "project_summary_count": len(project_summaries),
        "project_context_kernel_count": len(project_context_kernels),
        "project_context_compaction_count": len(project_context_compaction),
        "decision_count": len(decision_log),
        "failure_pattern_count": len(failure_patterns),
        "escalation_count": len(escalation_inbox),
        "dialogue_session_count": dialogue_memory.get("session_count", 0),
        "dialogue_message_count": dialogue_memory.get("message_count", 0),
        "dialogue_recent_topics": dialogue_memory.get("recent_topics", [])[:8],
        "dialogue_active_handoff": dialogue_memory.get("active_handoff", {}),
    }

    outputs = {
        'hot_context.json': hot_context,
        'project_summaries.json': project_summaries,
        'project_context_kernels.json': project_context_kernels,
        'project_context_compaction.json': project_context_compaction,
        'decision_log.json': decision_log,
        'failure_patterns.json': failure_patterns,
        'escalation_inbox.json': escalation_inbox,
        'context_kernel.json': context_kernel,
    }
    for name, payload in outputs.items():
        atomic_write_json(DATA / name, payload)
    return context_kernel

class RuntimeContextKernel:
    def __init__(
        self,
        data_dir: Path | None = None,
        *,
        admission_inline_chars: int = 600,
        summary_chars: int = 480,
        retrieval_chars: int = 1200,
        store_line_threshold: int = 40,
        max_recent_entries: int = 2000,
    ) -> None:
        self._data_dir = data_dir or DATA
        self._runtime_dir = self._data_dir / 'runtime_context'
        self._artifact_dir = self._runtime_dir / 'artifacts'
        self._index_path = self._runtime_dir / 'artifact_index.json'
        self._admission_inline_chars = max(120, admission_inline_chars)
        self._summary_chars = max(160, summary_chars)
        self._retrieval_chars = max(self._summary_chars, retrieval_chars)
        self._store_line_threshold = max(8, store_line_threshold)
        self._max_recent_entries = max(50, max_recent_entries)

    def admit(self, data: Any, *, channel: str = 'tool-output') -> dict[str, Any]:
        text = self._coerce_text(data)
        non_empty_lines = [line for line in text.splitlines() if line.strip()]
        char_count = len(text)
        line_count = len(non_empty_lines)
        should_store = bool(text.strip()) and (
            char_count > self._admission_inline_chars
            or line_count > self._store_line_threshold
            or channel in {'tool-output', 'shell-output', 'docker-output'}
        )
        return {
            'channel': channel,
            'char_count': char_count,
            'line_count': line_count,
            'store_raw': should_store,
            'inline_budget': min(char_count, self._admission_inline_chars),
        }

    def summarize(self, data: Any, *, title: str = '', channel: str = 'tool-output', max_chars: int | None = None) -> str:
        text = self._coerce_text(data)
        max_chars = max_chars or self._summary_chars
        label = (title or channel or 'context artifact').strip()
        if not text.strip():
            return f'{label}: no output.'

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        head = lines[:4]
        tail = lines[-3:] if len(lines) > 7 else []
        summary_lines = [f'{label}: {len(text)} chars, {len(lines)} non-empty lines.']

        parsed = self._try_parse_json(text)
        if isinstance(parsed, dict):
            keys = list(parsed.keys())[:8]
            if keys:
                summary_lines.append('Top-level keys: ' + ', '.join(str(key) for key in keys))
        elif isinstance(parsed, list):
            summary_lines.append(f'JSON array items: {len(parsed)}')

        if head:
            summary_lines.append('Head:')
            summary_lines.extend(f'- {self._clip_line(line, 160)}' for line in head)
        if tail:
            summary_lines.append('Tail:')
            summary_lines.extend(f'- {self._clip_line(line, 160)}' for line in tail)

        summary = '\n'.join(summary_lines).strip()
        if len(summary) <= max_chars:
            return summary
        return summary[: max_chars - 3].rstrip() + '...'

    def store(
        self,
        *,
        task_id: str,
        step_id: str | None,
        channel: str,
        title: str,
        data: Any,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = self._coerce_text(data)
        artifact_id = f'ctx_{uuid4().hex[:12]}'
        task_dir = self._artifact_dir / (task_id or 'orphan-task')
        suffix = '.json' if self._looks_like_json(text) else '.txt'
        stem = '-'.join(part for part in [step_id or 'task', channel.replace('_', '-'), artifact_id] if part)
        path = task_dir / f'{stem}{suffix}'
        atomic_write_text(path, text)

        entry = {
            'artifact_id': artifact_id,
            'task_id': task_id,
            'step_id': step_id,
            'channel': channel,
            'title': title,
            'path': str(path),
            'size_chars': len(text),
            'line_count': len([line for line in text.splitlines() if line.strip()]),
            'created_at': _utc(),
            'metadata': metadata or {},
        }
        index = self._load_index()
        entries = index.setdefault('entries', {})
        entries[artifact_id] = entry
        recent = [item for item in index.get('recent_ids', []) if item != artifact_id]
        recent.insert(0, artifact_id)
        index['recent_ids'] = recent[: self._max_recent_entries]
        index['updated_at'] = _utc()
        atomic_write_json(self._index_path, index)
        return entry

    def retrieve(self, artifact_id: str, *, max_chars: int | None = None) -> dict[str, Any] | None:
        index = self._load_index()
        entry = (index.get('entries') or {}).get(artifact_id)
        if not isinstance(entry, dict):
            return None
        path = Path(str(entry.get('path') or ''))
        if not path.exists():
            return {**entry, 'content': '', 'missing': True, 'truncated': False}
        content = path.read_text(encoding='utf-8', errors='replace')
        truncated = False
        if max_chars is not None and len(content) > max_chars:
            content = self._excerpt_text(content, max_chars=max_chars)
            truncated = True
        return {**entry, 'content': content, 'missing': False, 'truncated': truncated}

    def materialize(
        self,
        *,
        task_id: str,
        step_id: str | None,
        channel: str,
        title: str,
        data: Any,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = self._coerce_text(data)
        decision = self.admit(text, channel=channel)
        summary = self.summarize(text, title=title, channel=channel)
        artifact_ref: dict[str, Any] = {}
        if decision.get('store_raw'):
            artifact_ref = self.store(
                task_id=task_id,
                step_id=step_id,
                channel=channel,
                title=title,
                data=text,
                metadata=metadata,
            )
            summary = f'{summary}\nRaw artifact: {artifact_ref.get("artifact_id")}'
        return {
            'summary': summary,
            'artifact_ref': artifact_ref,
            'stats': {
                'channel': channel,
                'char_count': decision.get('char_count', 0),
                'line_count': decision.get('line_count', 0),
                'stored_raw': bool(artifact_ref),
            },
        }

    def render_for_prompt(
        self,
        artifact_ref: dict[str, Any] | None,
        *,
        fallback: str | None = None,
        max_chars: int | None = None,
    ) -> str:
        max_chars = max_chars or self._retrieval_chars
        if artifact_ref and artifact_ref.get('artifact_id'):
            payload = self.retrieve(str(artifact_ref.get('artifact_id')), max_chars=max_chars)
            if payload and payload.get('content'):
                summary = self.summarize(
                    payload.get('content', ''),
                    title=str(artifact_ref.get('title') or artifact_ref.get('channel') or 'artifact'),
                    channel=str(artifact_ref.get('channel') or 'artifact'),
                    max_chars=max_chars,
                )
                return f'{summary}\nArtifact ref: {artifact_ref.get("artifact_id")}'
        return self.summarize(fallback or '', title='Observed output', channel='inline-output', max_chars=max_chars)

    def list_task_artifacts(self, task_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        entries = list((self._load_index().get('entries') or {}).values())
        filtered = [item for item in entries if str(item.get('task_id') or '') == str(task_id)]
        filtered.sort(key=lambda item: str(item.get('created_at') or ''), reverse=True)
        return filtered[: max(1, limit)]

    def _load_index(self) -> dict[str, Any]:
        return _load_json(self._index_path, {'updated_at': None, 'recent_ids': [], 'entries': {}})

    def _coerce_text(self, data: Any) -> str:
        if data is None:
            return ''
        if isinstance(data, str):
            return data
        if isinstance(data, (dict, list)):
            return json.dumps(data, ensure_ascii=False, indent=2)
        return str(data)

    def _try_parse_json(self, text: str) -> Any:
        stripped = text.strip()
        if not stripped or stripped[0] not in '{[':
            return None
        try:
            return json.loads(stripped)
        except Exception:
            return None

    def _looks_like_json(self, text: str) -> bool:
        return self._try_parse_json(text) is not None

    def _clip_line(self, text: str, limit: int) -> str:
        cleaned = ' '.join(str(text).split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + '...'

    def _excerpt_text(self, text: str, *, max_chars: int) -> str:
        stripped = text.strip()
        if len(stripped) <= max_chars:
            return stripped
        head_budget = max(80, max_chars // 2)
        tail_budget = max(40, max_chars - head_budget - 16)
        head = stripped[:head_budget].rstrip()
        tail = stripped[-tail_budget:].lstrip()
        return f'{head}\n...\n{tail}'

if __name__ == '__main__':
    print(json.dumps(rebuild(), ensure_ascii=False, indent=2))

