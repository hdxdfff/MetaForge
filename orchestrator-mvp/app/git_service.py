from __future__ import annotations

import asyncio
import shutil
import shlex
from dataclasses import dataclass
from pathlib import Path

from .models import RepoPushRequest, RepoPushResult, RepoRecord

APP_ROOT = Path(__file__).resolve().parent.parent
CODEX_ROOT = APP_ROOT.parent
GIT_EXE = CODEX_ROOT / "tools" / "mingit-2.53.0-64-bit" / "mingw64" / "bin" / "git.exe"


class GitServiceError(RuntimeError):
    pass


@dataclass
class GitCommandResult:
    stdout: str
    stderr: str
    returncode: int


class GitService:
    async def ensure_repo(self, repo: RepoRecord) -> None:
        git_dir = Path(repo.local_path) / ".git"
        if git_dir.exists():
            return
        result = await self._run_git(repo.local_path, "git rev-parse --git-dir")
        if result.returncode != 0:
            raise GitServiceError(f"Not a git repository: {repo.local_path}")

    async def sync_remotes(self, repo: RepoRecord) -> str:
        await self.ensure_repo(repo)
        outputs: list[str] = []
        for remote in repo.remotes:
            check = await self._run_git(repo.local_path, f"git remote get-url {shlex.quote(remote.name)}")
            if check.returncode == 0:
                await self._run_git(repo.local_path, f"git remote set-url {shlex.quote(remote.name)} {shlex.quote(remote.url)}")
                outputs.append(f"updated remote {remote.name}")
            else:
                await self._run_git(repo.local_path, f"git remote add {shlex.quote(remote.name)} {shlex.quote(remote.url)}")
                outputs.append(f"added remote {remote.name}")
        return "\n".join(outputs)

    async def current_branch(self, repo: RepoRecord) -> str:
        await self.ensure_repo(repo)
        result = await self._run_git(repo.local_path, "git branch --show-current")
        branch = result.stdout.strip()
        if result.returncode != 0 or not branch:
            return repo.default_branch
        return branch

    async def status_summary(self, repo: RepoRecord) -> str:
        await self.ensure_repo(repo)
        result = await self._run_git(repo.local_path, "git status --short --branch")
        if result.returncode != 0:
            raise GitServiceError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()



    async def suggest_feature_branch(self, repo: RepoRecord, prompt: str) -> str:
        slug = ''.join(ch.lower() if ch.isalnum() else '-' for ch in prompt[:40]).strip('-')
        slug = '-'.join(part for part in slug.split('-') if part) or 'task'
        return f"codex/{slug[:48]}"

    async def branch_exists(self, repo: RepoRecord, branch: str) -> bool:
        result = await self._run_git(repo.local_path, f"git branch --list {shlex.quote(branch)}")
        return result.returncode == 0 and bool(result.stdout.strip())

    async def commit_summary(self, repo: RepoRecord) -> str:
        result = await self._run_git(repo.local_path, "git diff --stat")
        if result.returncode != 0:
            raise GitServiceError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()



    async def ensure_feature_branch(self, repo: RepoRecord, prompt: str) -> dict[str, str]:
        await self.ensure_repo(repo)
        branch = await self.suggest_feature_branch(repo, prompt)
        exists = await self.branch_exists(repo, branch)
        if exists:
            result = await self._run_git(repo.local_path, f"git checkout {shlex.quote(branch)}")
        else:
            result = await self._run_git(repo.local_path, f"git checkout -b {shlex.quote(branch)}")
        if result.returncode != 0:
            raise GitServiceError(result.stderr.strip() or result.stdout.strip())
        return {"branch": branch, "created": str(not exists).lower(), "output": (result.stdout or result.stderr).strip()}

    async def push(self, repo: RepoRecord, payload: RepoPushRequest) -> RepoPushResult:
        await self.ensure_repo(repo)
        sync_output = await self.sync_remotes(repo)
        branch = payload.branch or await self.current_branch(repo)
        remotes = payload.remote_names or [remote.name for remote in repo.remotes]
        if not remotes:
            raise GitServiceError("No remotes configured for this repo.")
        outputs = [sync_output] if sync_output else []
        for remote_name in remotes:
            command = f"git push {'-u ' if payload.set_upstream else ''}{shlex.quote(remote_name)} {shlex.quote(branch)}"
            result = await self._run_git(repo.local_path, command)
            if result.returncode != 0:
                raise GitServiceError(result.stderr.strip() or result.stdout.strip())
            outputs.append(f"[{remote_name}]\n{result.stdout.strip()}")
        return RepoPushResult(repo_id=repo.id, branch=branch, pushed_remotes=remotes, output="\n\n".join(item for item in outputs if item))

    async def _run_git(self, workdir: str, command: str) -> GitCommandResult:
        executable = str(GIT_EXE) if GIT_EXE.exists() else (shutil.which("git") or "git")
        proc = await asyncio.create_subprocess_exec(
            executable,
            *shlex.split(command),
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return GitCommandResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            returncode=proc.returncode,
        )
