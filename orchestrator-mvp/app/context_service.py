from __future__ import annotations

from pathlib import Path

from .git_service import GitService, GitServiceError
from .models import ContextEnvelope, ContextMode, RepoRecord, TaskCreate
from .resource_registry import ResourceRegistry


class ContextService:
    def __init__(self, registry: ResourceRegistry, git_service: GitService) -> None:
        self._registry = registry
        self._git = git_service

    async def build(self, payload: TaskCreate) -> ContextEnvelope:
        envelope = ContextEnvelope(
            mode=payload.context_mode, budget_chars=max(400, payload.max_context_chars)
        )

        self._append(
            envelope,
            f"Task goal: {payload.goal or 'not specified'}\nRepo path: {payload.repo_path or 'not provided'}\nContext mode: {payload.context_mode.value}",
            "task-brief",
        )

        if payload.allow_resource_scan:
            self._append(envelope, self._resource_summary(payload.context_mode), "resource-summary")

        if (
            payload.allow_repo_status
            and payload.repo_path
            and payload.context_mode in {ContextMode.standard, ContextMode.deep}
        ):
            repo_summary = await self._repo_summary(payload.repo_path)
            if repo_summary:
                self._append(envelope, repo_summary, "repo-status")

        return envelope

    def _resource_summary(self, mode: ContextMode) -> str:
        resources = self._registry.list_resources()
        if mode == ContextMode.lean:
            resources = [
                resource
                for resource in resources
                if resource.kind.value in {"runtime", "model", "tool"}
            ][:5]
        elif mode == ContextMode.standard:
            resources = resources[:8]

        lines = ["Available resources:"]
        for resource in resources:
            lines.append(
                f"- {resource.name} [{resource.kind}] status={resource.status} location={resource.location or 'n/a'}"
            )
        return "\n".join(lines)

    async def _repo_summary(self, repo_path: str) -> str | None:
        repo = RepoRecord(name=Path(repo_path).name or "repo", local_path=repo_path)
        try:
            branch = await self._git.current_branch(repo)
            status = await self._git.status_summary(repo)
        except GitServiceError:
            return None
        status_lines = status.splitlines()[:8]
        return "\n".join(
            [
                f"Repository branch: {branch}",
                "Repository git status:",
                *status_lines,
            ]
        )

    def _append(self, envelope: ContextEnvelope, block: str, label: str) -> None:
        remaining = envelope.budget_chars - envelope.used_chars
        if remaining <= 0:
            return
        trimmed = block[:remaining]
        if not trimmed:
            return
        envelope.summary_blocks.append(trimmed)
        envelope.includes.append(label)
        envelope.used_chars += len(trimmed)
