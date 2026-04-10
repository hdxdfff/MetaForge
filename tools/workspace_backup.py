from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_ROOT = DEFAULT_ROOT / "backups"
BACKUP_DIR_PREFIX = "backup_"
BACKUP_DIR_EXCLUDES = ("backups", "backups/")


@dataclass(slots=True)
class ChangeRecord:
    status: str
    path: str
    original_path: str | None = None
    copied: bool = False
    reason: str | None = None


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _git_text(args: list[str], *, cwd: Path) -> str:
    result = _run_git(args, cwd=cwd)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"git {' '.join(args)} failed")
    return (result.stdout or b"").decode("utf-8", errors="replace").strip()


def _git_bytes(args: list[str], *, cwd: Path) -> bytes:
    result = _run_git(args, cwd=cwd)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"git {' '.join(args)} failed")
    return result.stdout or b""


def _repo_root(root: Path | None) -> Path:
    candidate = (root or DEFAULT_ROOT).resolve()
    result = _git_text(["rev-parse", "--show-toplevel"], cwd=candidate)
    return Path(result).resolve()


def _current_branch(root: Path) -> str:
    branch = _git_text(["branch", "--show-current"], cwd=root)
    return branch or "HEAD"


def _head_commit(root: Path) -> str:
    return _git_text(["rev-parse", "HEAD"], cwd=root)


def _status_entries(root: Path) -> list[ChangeRecord]:
    raw = _git_bytes(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=root)
    if not raw:
        return []

    tokens = raw.split(b"\0")
    records: list[ChangeRecord] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue

        status = token[:2].decode("ascii", errors="replace")
        path = token[3:].decode("utf-8", errors="replace")
        if status[:1] in {"R", "C"}:
            index += 1
            if index >= len(tokens):
                records.append(ChangeRecord(status=status, path=path, original_path=None, copied=False, reason="missing rename target"))
                break
            target = tokens[index].decode("utf-8", errors="replace")
            records.append(ChangeRecord(status=status, path=target, original_path=path))
        else:
            records.append(ChangeRecord(status=status, path=path))
        index += 1
    return records


def _normalize_relpath(root: Path, relpath: str) -> Path:
    normalized = Path(relpath.replace("/", os.sep))
    candidate = (root / normalized).resolve()
    candidate.relative_to(root)
    return candidate


def _should_exclude(relpath: str) -> bool:
    normalized = relpath.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == "backups" or normalized.startswith("backups/")


def _copy_changed_files(root: Path, backup_dir: Path, records: Iterable[ChangeRecord]) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    for record in records:
        if _should_exclude(record.path):
            record.reason = "excluded backup workspace"
            copied.append(
                {
                    "status": record.status,
                    "path": record.path,
                    "original_path": record.original_path,
                    "copied": False,
                    "reason": record.reason,
                }
            )
            continue

        source_path = _normalize_relpath(root, record.path)
        rel_target = Path(record.path.replace("/", os.sep))
        target_path = backup_dir / rel_target
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if source_path.exists() and source_path.is_file():
            shutil.copy2(source_path, target_path)
            record.copied = True
            copied.append(
                {
                    "status": record.status,
                    "path": record.path,
                    "original_path": record.original_path,
                    "copied": True,
                    "backup_path": str(target_path),
                }
            )
        else:
            record.reason = "missing source file"
            copied.append(
                {
                    "status": record.status,
                    "path": record.path,
                    "original_path": record.original_path,
                    "copied": False,
                    "reason": record.reason,
                }
            )
    return copied


def _create_backup_dir(backup_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_dir = backup_root / f"{BACKUP_DIR_PREFIX}{stamp}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = backup_root / f"{BACKUP_DIR_PREFIX}{stamp}_{suffix}"
        suffix += 1
    backup_dir.mkdir(parents=True, exist_ok=False)
    return backup_dir


def _write_manifest(
    backup_dir: Path,
    *,
    root: Path,
    branch: str,
    head_commit: str,
    records: list[dict[str, object]],
    purpose: str,
) -> Path:
    manifest = {
        "version": 1,
        "purpose": purpose,
        "generated_at": datetime.now().astimezone().isoformat(),
        "workspace_root": str(root),
        "branch": branch,
        "head_commit": head_commit,
        "changed_count": len(records),
        "copied_count": sum(1 for item in records if item.get("copied")),
        "records": records,
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def _stage_changes(root: Path, records: Iterable[dict[str, object]]) -> None:
    paths: list[str] = []
    for record in records:
        path = str(record.get("path") or "").strip()
        original_path = str(record.get("original_path") or "").strip()
        for candidate in (original_path, path):
            if not candidate:
                continue
            if _should_exclude(candidate):
                continue
            if candidate not in paths:
                paths.append(candidate)

    if not paths:
        return

    result = _run_git(["add", "-A", "--", *paths], cwd=root)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "git add failed")


def _has_staged_changes(root: Path) -> bool:
    result = _run_git(["diff", "--cached", "--quiet"], cwd=root)
    return result.returncode != 0


def _commit(root: Path, message: str) -> str:
    result = _run_git(["commit", "-m", message], cwd=root)
    if result.returncode != 0:
        message_text = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(message_text or "git commit failed")
    return (result.stdout or b"").decode("utf-8", errors="replace").strip()


def _push(root: Path, remote: str) -> str:
    branch = _current_branch(root)
    result = _run_git(["push", "-u", remote, branch], cwd=root)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "git push failed")
    return (result.stdout or b"").decode("utf-8", errors="replace").strip()


def _status_summary(root: Path) -> str:
    return _git_text(["status", "--short", "--branch"], cwd=root)


def snapshot_workspace(root: Path, backup_root: Path | None = None) -> dict[str, object]:
    workspace_root = _repo_root(root)
    backup_root = (backup_root or DEFAULT_BACKUP_ROOT).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)

    branch = _current_branch(workspace_root)
    head_commit = _head_commit(workspace_root)
    records = _status_entries(workspace_root)
    backup_dir = _create_backup_dir(backup_root)
    copied_records = _copy_changed_files(workspace_root, backup_dir, records)
    manifest_path = _write_manifest(
        backup_dir,
        root=workspace_root,
        branch=branch,
        head_commit=head_commit,
        records=copied_records,
        purpose="local snapshot",
    )
    return {
        "workspace_root": str(workspace_root),
        "branch": branch,
        "head_commit": head_commit,
        "backup_dir": str(backup_dir),
        "manifest_path": str(manifest_path),
        "status": _status_summary(workspace_root),
        "records": copied_records,
    }


def publish_workspace(root: Path, *, message: str, remote: str = "origin", backup_root: Path | None = None) -> dict[str, object]:
    workspace_root = _repo_root(root)
    backup_result = snapshot_workspace(workspace_root, backup_root)
    _stage_changes(workspace_root, backup_result["records"])

    staged = _has_staged_changes(workspace_root)
    commit_output = ""
    commit_hash = _head_commit(workspace_root)
    if staged:
        commit_output = _commit(workspace_root, message)
        commit_hash = _head_commit(workspace_root)

    push_output = ""
    if staged:
        push_output = _push(workspace_root, remote)

    result = {
        "workspace_root": str(workspace_root),
        "branch": _current_branch(workspace_root),
        "head_commit": commit_hash,
        "backup_dir": backup_result["backup_dir"],
        "manifest_path": backup_result["manifest_path"],
        "commit_output": commit_output,
        "push_output": push_output,
        "status": _status_summary(workspace_root),
        "records": backup_result["records"],
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create local workspace backups and optionally publish them to GitHub.")
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Workspace root. Defaults to D:\\codex.")
    parent.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT, help="Backup destination. Defaults to D:\\codex\\backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot", parents=[parent], help="Create a local backup snapshot only.")
    snapshot_parser.set_defaults(command="snapshot")

    publish_parser = subparsers.add_parser("publish", parents=[parent], help="Create a local snapshot, commit the workspace changes, and push them.")
    publish_parser.add_argument("--message", default=None, help="Git commit message. Defaults to a timestamped backup message.")
    publish_parser.add_argument("--remote", default="origin", help="Git remote name. Defaults to origin.")
    publish_parser.set_defaults(command="publish")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = args.root
    backup_root = args.backup_root

    if args.command == "snapshot":
        result = snapshot_workspace(root, backup_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "publish":
        message = args.message or f"Backup workspace changes {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        result = publish_workspace(root, message=message, remote=args.remote, backup_root=backup_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
