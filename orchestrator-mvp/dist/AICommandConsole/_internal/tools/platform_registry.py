from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
FACTORY = ROOT / "factory"
REGISTRY = FACTORY / "platform_registry.json"
TEMPLATES = ROOT / "templates" / "systems"
PLATFORM_WORKSPACE = FACTORY / "workspace"
WORKSPACE_ROOT = ROOT / "workspace"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def normalize_workspace_path(workspace: str | None) -> str | None:
    if not workspace:
        return workspace
    current = Path(workspace)
    if current.exists():
        return str(current)
    alternate = WORKSPACE_ROOT / current.name
    if alternate.exists():
        return str(alternate)
    return str(current)


def list_templates() -> list[dict[str, Any]]:
    items = []
    for template_dir in sorted(TEMPLATES.iterdir()):
        if not template_dir.is_dir():
            continue
        manifest = _load_json(template_dir / "template.json", {})
        items.append(
            {
                "template_id": template_dir.name,
                "description": manifest.get("description"),
                "required_paths": manifest.get("required_paths", []),
                "generator_outputs": manifest.get("generator_outputs", []),
            }
        )
    return items


def _infer_runtime(item: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(item.get("workspace") or "")
    required = item.get("required_paths") or []
    present = 0
    if workspace.exists():
        for rel in required:
            if (workspace / rel).exists():
                present += 1
    runtime = dict(item.get("runtime") or {})
    runtime.setdefault("backend", "workspace")
    runtime.setdefault("last_checked", _utc())
    runtime.setdefault("last_run", runtime.get("last_run"))
    if workspace.exists() and required and present == len(required):
        runtime["health"] = "healthy"
        runtime["status"] = (
            runtime.get("status") if runtime.get("status") in {"running", "active"} else "ready"
        )
    elif workspace.exists():
        runtime["health"] = "degraded"
        runtime["status"] = (
            runtime.get("status") if runtime.get("status") in {"running", "active"} else "generated"
        )
    else:
        runtime["health"] = "missing"
        runtime["status"] = "missing"
    runtime["required_paths_present"] = present
    runtime["required_paths_total"] = len(required)
    return runtime


def load_registry() -> dict[str, Any]:
    registry = _load_json(REGISTRY, {"updated_at": None, "platforms": []})
    changed = False
    for item in registry.get("platforms", []):
        normalized = normalize_workspace_path(item.get("workspace"))
        if normalized != item.get("workspace"):
            item["workspace"] = normalized
            changed = True
        inferred = _infer_runtime(item)
        if item.get("runtime") != inferred:
            item["runtime"] = inferred
            changed = True
    if changed:
        save_registry(registry)
    return registry


def save_registry(registry: dict[str, Any]) -> None:
    registry["updated_at"] = _utc()
    _save_json(REGISTRY, registry)


def register_platform(platform: dict[str, Any]) -> dict[str, Any]:
    registry = load_registry()
    platform["workspace"] = normalize_workspace_path(platform.get("workspace"))
    platforms = [
        item
        for item in registry.get("platforms", [])
        if item.get("platform_id") != platform.get("platform_id")
    ]
    platforms.append(platform)
    registry["platforms"] = platforms
    save_registry(registry)
    return platform


def list_platforms() -> list[dict[str, Any]]:
    return load_registry().get("platforms", [])


def update_platform_runtime(platform_id: str, **fields: Any) -> dict[str, Any]:
    registry = load_registry()
    for item in registry.get("platforms", []):
        if item.get("platform_id") != platform_id:
            continue
        runtime = item.setdefault("runtime", {})
        runtime.update(fields)
        runtime["updated_at"] = _utc()
        runtime["last_checked"] = _utc()
        save_registry(registry)
        return item
    raise RuntimeError(f"Platform not found: {platform_id}")


def platform_health_summary() -> dict[str, Any]:
    platforms = list_platforms()
    active = [
        item
        for item in platforms
        if (item.get("runtime") or {}).get("status") in {"running", "active", "healthy"}
    ]
    unhealthy = [
        item
        for item in platforms
        if (item.get("runtime") or {}).get("health") in {"degraded", "failed"}
    ]
    return {
        "platform_count": len(platforms),
        "active_count": len(active),
        "unhealthy_count": len(unhealthy),
        "platforms": [
            {
                "platform_id": item.get("platform_id"),
                "name": item.get("name"),
                "status": (item.get("runtime") or {}).get(
                    "status", item.get("status", "generated")
                ),
                "health": (item.get("runtime") or {}).get("health", "unknown"),
                "last_run": (item.get("runtime") or {}).get("last_run"),
            }
            for item in platforms
        ],
    }
