from __future__ import annotations

import json
from pathlib import Path

from .models import RepoRecord, RepoRegistration, RepoRemote, ResourceKind, ResourceRecord


class ResourceRegistry:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._resources_file = root / "resources.json"
        self._repos_file = root / "repos.json"
        self._resources: dict[str, ResourceRecord] = {}
        self._repos: dict[str, RepoRecord] = {}
        self._load()
        self._ensure_defaults()

    def list_resources(self) -> list[ResourceRecord]:
        return sorted(self._resources.values(), key=lambda item: item.name.lower())

    def list_repos(self) -> list[RepoRecord]:
        return sorted(self._repos.values(), key=lambda item: item.name.lower())

    def get_repo(self, repo_id: str) -> RepoRecord | None:
        return self._repos.get(repo_id)

    def upsert_repo(self, payload: RepoRegistration) -> RepoRecord:
        existing = next((repo for repo in self._repos.values() if Path(repo.local_path) == Path(payload.local_path)), None)
        remotes: list[RepoRemote] = []
        if payload.github_url:
            remotes.append(RepoRemote(name="github", url=payload.github_url, provider="github"))
        if payload.gitee_url:
            remotes.append(RepoRemote(name="gitee", url=payload.gitee_url, provider="gitee"))
        if existing:
            existing.name = payload.name
            existing.local_path = payload.local_path
            existing.default_branch = payload.default_branch
            existing.remotes = remotes
            self._persist()
            return existing
        repo = RepoRecord(name=payload.name, local_path=payload.local_path, default_branch=payload.default_branch, remotes=remotes)
        self._repos[repo.id] = repo
        self._persist()
        return repo

    def mark_repo_pushed(self, repo_id: str) -> None:
        repo = self._repos[repo_id]
        repo.last_push_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        self._persist()

    def _load(self) -> None:
        if self._resources_file.exists():
            try:
                for item in json.loads(self._resources_file.read_text(encoding="utf-8")):
                    resource = ResourceRecord.model_validate(item)
                    self._resources[resource.id] = resource
            except Exception:
                self._resources = {}
        if self._repos_file.exists():
            try:
                for item in json.loads(self._repos_file.read_text(encoding="utf-8")):
                    repo = RepoRecord.model_validate(item)
                    self._repos[repo.id] = repo
            except Exception:
                self._repos = {}

    def _ensure_defaults(self) -> None:
        defaults = [
            ("sandbox-runtime", "Local Sandbox Runtime", ResourceKind.runtime, "available", "Docker / local VM", {"backend": "sandbox-vm"}),
            ("open-interpreter", "Open Interpreter", ResourceKind.tool, "available", "D:\\codex\\open-interpreter.cmd", {}),
            ("docker", "Docker", ResourceKind.container, "available", "docker-desktop", {}),
            ("network-lab-workspace", "Computer Network Lab Workspace", ResourceKind.runtime, "available", "D:\\计算机网络", {"role": "network-course-workspace"}),
            ("wireshark-bundle", "Wireshark Bundle", ResourceKind.tool, "available", "D:\\计算机网络\\Wireshark\\Wireshark.exe", {"role": "packet-analysis", "family": "network"}),
            ("tcpdump-cli", "tcpdump CLI", ResourceKind.tool, "optional", "D:\\计算机网络\\Wireshark\\dumpcap.exe", {"role": "packet-capture", "family": "network"}),
            ("curl-cli", "curl CLI", ResourceKind.tool, "available", "curl", {"role": "http-client", "family": "network"}),
            ("database-lab-workspace", "Database Systems Lab Workspace", ResourceKind.runtime, "available", "D:\\数据库系统", {"role": "database-course-workspace", "note": "documents detected; runtime not yet confirmed"}),
            ("frontend-study-workspace", "Frontend Study Workspace", ResourceKind.runtime, "available", "D:\\前端学习资料", {"role": "frontend-course-workspace"}),
            ("ai-math-workspace", "AI Math Foundations Workspace", ResourceKind.runtime, "available", "D:\\人工智能数学基础", {"role": "math-course-workspace"}),
            ("mysql-cli", "MySQL CLI", ResourceKind.tool, "optional", "mysql", {"role": "database-client", "family": "mysql"}),
            ("mysql-server", "MySQL Server", ResourceKind.runtime, "optional", "localhost:3306", {"role": "database-runtime", "family": "mysql"}),
            ("release-records", "Release Records", ResourceKind.runtime, "available", "D:\codex\orchestrator-mvp\data\release_records.json", {"role": "release-history"}),
            ("deploy-target-local", "Local Deploy Target", ResourceKind.runtime, "optional", "local-workspace", {"role": "deploy-target", "scope": "local"}),
            ("cline", "Cline", ResourceKind.ide, "available", "VS Code", {}),
            ("autogpt", "AutoGPT Classic", ResourceKind.tool, "available", "D:\\codex\\agents\\autogpt-classic", {}),
            ("crewai", "CrewAI Starter", ResourceKind.tool, "available", "D:\\codex\\agents\\crewai-starter", {}),
            ("planner-openai", "GPT Planner", ResourceKind.model, "configured", "http://localhost:11434", {"role": "planner", "family": "openai-compatible"}),
            ("local-llm-gateway", "Local LLM Gateway", ResourceKind.runtime, "available", "http://localhost:11434", {"role": "unified-model-gateway", "family": "openai-compatible"}),
            ("cheap-lane", "Cheap Model Lane", ResourceKind.model, "optional", "http://localhost:11434", {"role": "coder-reviewer-summary", "family": "openai-compatible"}),
            ("browser-automation-bridge", "Browser Automation Bridge", ResourceKind.tool, "available", "D:\\codex\\tools\\browser-automation\\read-page.ps1", {"role": "real-browser-reading", "browser": "edge-or-chrome", "family": "playwright-core"}),
        ]
        known_names = {resource.name for resource in self._resources.values()}
        changed = False
        for stable_id, name, kind, status, location, metadata in defaults:
            if name in known_names:
                continue
            resource = ResourceRecord(id=stable_id, name=name, kind=kind, status=status, location=location, metadata=metadata)
            self._resources[resource.id] = resource
            changed = True
        if changed:
            self._persist()

    def _persist(self) -> None:
        self._resources_file.write_text(
            json.dumps([item.model_dump(mode="json") for item in self._resources.values()], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._repos_file.write_text(
            json.dumps([item.model_dump(mode="json") for item in self._repos.values()], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
