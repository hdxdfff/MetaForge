from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PREFERRED_ROOTS = (
    Path("/workspace/generated"),
    Path("/srv/orchestrator-mvp/generated"),
)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_generated_root() -> Path:
    for root in PREFERRED_ROOTS:
        if root.exists():
            return root
    return PREFERRED_ROOTS[0]


def build_manifest(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    newest_mtime = 0.0
    total_size = 0

    if root.exists():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if ".git" in path.parts:
                continue
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
            mtime = float(stat.st_mtime)
            size = int(stat.st_size)
            newest_mtime = max(newest_mtime, mtime)
            total_size += size
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            digest.update(f"{mtime:.6f}".encode("ascii"))
            digest.update(b"\0")
            files.append(
                {
                    "path": relative,
                    "size": size,
                    "mtime": mtime,
                }
            )

    return {
        "status": "ok",
        "generated_root": str(root),
        "file_count": len(files),
        "total_size": total_size,
        "fingerprint": digest.hexdigest(),
        "newest_mtime": newest_mtime,
        "newest_mtime_iso": _utc_iso(datetime.fromtimestamp(newest_mtime, tz=timezone.utc)) if newest_mtime else None,
        "files": files,
        "generated_at": _utc_iso(datetime.now(timezone.utc)),
    }


def build_bundle(root: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(
            root,
            arcname="generated",
            filter=lambda info: None if ".git" in Path(info.name).parts else info,
        )
    stat = output_path.stat()
    return {
        "status": "ok",
        "generated_root": str(root),
        "bundle_path": str(output_path),
        "bundle_size": int(stat.st_size),
        "generated_at": _utc_iso(datetime.now(timezone.utc)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="generated_sync_manifest")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest")
    bundle = sub.add_parser("bundle")
    bundle.add_argument("--output", required=True)
    args = parser.parse_args()

    root = resolve_generated_root()
    if args.command == "manifest":
        print(json.dumps(build_manifest(root), ensure_ascii=False))
        return 0

    output_path = Path(args.output)
    print(json.dumps(build_bundle(root, output_path), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
