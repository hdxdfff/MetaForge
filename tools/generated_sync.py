from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(r"D:\codex")
VMCTL = ROOT / "vm-entry.cmd"
REMOTE_PYTHON = "/srv/orchestrator-mvp/.venv/bin/python"
REMOTE_HELPER = "/srv/orchestrator-mvp/tools/generated_sync_manifest.py"
HOST_GENERATED = ROOT / "generated"
SYNC_STATE_DIR = HOST_GENERATED / ".vm-sync"
SYNC_STATUS_FILE = SYNC_STATE_DIR / "status.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _run_vmctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VMCTL), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _load_json_text(text: str) -> Any:
    value = text.strip()
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        for line in reversed(lines):
            if line.startswith("{") or line.startswith("["):
                try:
                    return json.loads(line)
                except Exception:
                    continue
    return {}


def _read_status() -> dict[str, Any]:
    if not SYNC_STATUS_FILE.exists():
        return {}
    try:
        return json.loads(SYNC_STATUS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _write_status(payload: dict[str, Any]) -> None:
    SYNC_STATE_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise RuntimeError(f"Refusing to extract outside destination: {member.name}")
        archive.extractall(destination)


def _remove_stale_files(previous_files: set[str], current_files: set[str]) -> list[str]:
    removed: list[str] = []
    for relative in sorted(previous_files - current_files, reverse=True):
        target = HOST_GENERATED / Path(relative)
        try:
            if target.is_file():
                target.unlink()
                removed.append(relative)
        except FileNotFoundError:
            continue
    for relative in sorted(previous_files - current_files, reverse=True):
        parent = (HOST_GENERATED / Path(relative)).parent
        while parent != HOST_GENERATED and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return removed


def _cleanup_disallowed_paths() -> list[str]:
    removed: list[str] = []
    for path in HOST_GENERATED.rglob(".git"):
        if not path.is_dir():
            continue
        def _clear_readonly(func, target, exc_info):
            try:
                os.chmod(target, 0o700)
            except OSError:
                pass
            func(target)

        try:
            shutil.rmtree(path, onerror=_clear_readonly)
            removed.append(str(path.relative_to(HOST_GENERATED)).replace("\\", "/"))
        except OSError:
            pass
    return removed


def _fetch_manifest() -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    result = _run_vmctl(["ssh", REMOTE_PYTHON, REMOTE_HELPER, "manifest"])
    return _load_json_text(result.stdout), result


def _create_remote_bundle(bundle_path: str) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    result = _run_vmctl(["ssh", REMOTE_PYTHON, REMOTE_HELPER, "bundle", "--output", bundle_path])
    return _load_json_text(result.stdout), result


def sync_generated(*, force: bool = False, quiet: bool = False, cooldown_seconds: int = 300, reason: str = "manual") -> dict[str, Any]:
    prior_status = _read_status()
    last_attempt = _parse_iso(prior_status.get("last_attempt_at"))
    now = _utc_now()
    if not force and last_attempt and now - last_attempt < timedelta(seconds=max(0, cooldown_seconds)):
        payload = {
            "status": "cooldown",
            "reason": reason,
            "cooldown_seconds": cooldown_seconds,
            "last_attempt_at": prior_status.get("last_attempt_at"),
            "last_sync_at": prior_status.get("last_sync_at"),
            "fingerprint": prior_status.get("fingerprint"),
        }
        if not quiet:
            print(json.dumps(payload, ensure_ascii=False))
        return payload

    manifest, manifest_result = _fetch_manifest()
    if manifest_result.returncode != 0:
        payload = {
            "status": "error",
            "reason": reason,
            "step": "manifest",
            "returncode": manifest_result.returncode,
            "stderr": manifest_result.stderr.strip(),
        }
        _write_status({**prior_status, "last_attempt_at": _iso_utc(now), "last_error": payload})
        if not quiet:
            print(json.dumps(payload, ensure_ascii=False))
        return payload

    fingerprint = str(manifest.get("fingerprint") or "")
    previous_fingerprint = str(prior_status.get("fingerprint") or "")
    current_files = {str(item.get("path")) for item in (manifest.get("files") or []) if isinstance(item, dict) and item.get("path")}
    if not force and fingerprint and fingerprint == previous_fingerprint:
        payload = {
            "status": "unchanged",
            "reason": reason,
            "fingerprint": fingerprint,
            "file_count": int(manifest.get("file_count") or 0),
            "generated_root": manifest.get("generated_root"),
            "last_sync_at": prior_status.get("last_sync_at"),
        }
        _write_status(
            {
                **prior_status,
                "last_attempt_at": _iso_utc(now),
                "last_result": payload,
            }
        )
        if not quiet:
            print(json.dumps(payload, ensure_ascii=False))
        return payload

    bundle_suffix = (fingerprint or "adhoc")[:12]
    remote_bundle = f"/tmp/codex-generated-sync-{bundle_suffix}.tar.gz"
    bundle_payload, bundle_result = _create_remote_bundle(remote_bundle)
    if bundle_result.returncode != 0:
        payload = {
            "status": "error",
            "reason": reason,
            "step": "bundle",
            "returncode": bundle_result.returncode,
            "stderr": bundle_result.stderr.strip(),
        }
        _write_status({**prior_status, "last_attempt_at": _iso_utc(now), "last_error": payload})
        if not quiet:
            print(json.dumps(payload, ensure_ascii=False))
        return payload

    SYNC_STATE_DIR.mkdir(parents=True, exist_ok=True)
    local_bundle = SYNC_STATE_DIR / f"bundle-{bundle_suffix}.tar.gz"
    get_result = _run_vmctl(["get", remote_bundle, str(local_bundle)])
    _run_vmctl(["ssh", "rm", "-f", remote_bundle])
    if get_result.returncode != 0:
        payload = {
            "status": "error",
            "reason": reason,
            "step": "download",
            "returncode": get_result.returncode,
            "stderr": get_result.stderr.strip(),
        }
        _write_status({**prior_status, "last_attempt_at": _iso_utc(now), "last_error": payload})
        if not quiet:
            print(json.dumps(payload, ensure_ascii=False))
        return payload

    HOST_GENERATED.mkdir(parents=True, exist_ok=True)
    disallowed_removed = _cleanup_disallowed_paths()
    _safe_extract(local_bundle, ROOT)
    previous_files = {str(item) for item in (prior_status.get("files") or []) if isinstance(item, str)}
    removed = _remove_stale_files(previous_files, current_files)

    payload = {
        "status": "synced",
        "reason": reason,
        "fingerprint": fingerprint,
        "generated_root": manifest.get("generated_root"),
        "file_count": int(manifest.get("file_count") or 0),
        "bundle_size": bundle_payload.get("bundle_size"),
        "removed_files": sorted(set(removed + disallowed_removed)),
        "host_generated_root": str(HOST_GENERATED),
        "last_sync_at": _iso_utc(now),
    }
    _write_status(
        {
            "last_attempt_at": _iso_utc(now),
            "last_sync_at": payload["last_sync_at"],
            "fingerprint": fingerprint,
            "generated_root": manifest.get("generated_root"),
            "file_count": int(manifest.get("file_count") or 0),
            "files": sorted(current_files),
            "last_result": payload,
        }
    )
    if not quiet:
        print(json.dumps(payload, ensure_ascii=False))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(prog="generated_sync")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--cooldown-seconds", type=int, default=300)
    parser.add_argument("--reason", default="manual")
    args = parser.parse_args()
    payload = sync_generated(
        force=args.force,
        quiet=args.quiet,
        cooldown_seconds=max(0, args.cooldown_seconds),
        reason=args.reason,
    )
    return 0 if payload.get("status") in {"synced", "unchanged", "cooldown"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
