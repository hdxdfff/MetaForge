from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
REPO_LEARNING = DATA / "repo_learning_state.json"
DISTILLATION = DATA / "capability_distillation.json"
LIBRARY = DATA / "github_capability_library.json"
REGISTRY = FACTORY / "capability_registry.json"
ASSET_ROOT = FACTORY / "agents" / "github_learning"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    parts = [part for part in text.split("-") if part]
    return "-".join(parts) or "unknown"


def _keywords(capability_id: str, repo: dict[str, Any]) -> list[str]:
    keywords = set(str(item).strip().lower() for item in (repo.get("capabilities") or []) if str(item).strip())
    keywords.update(str(item).strip().lower() for item in ((repo.get("topics") or [])[:8]) if str(item).strip())
    keywords.update(part for part in capability_id.replace("_", "-").split("-") if part)
    return sorted(keywords)


def refresh_github_capability_library() -> dict[str, Any]:
    repo_learning = _load_json(REPO_LEARNING, {})
    distillation = _load_json(DISTILLATION, {})
    registry = _load_json(REGISTRY, {"updated_at": None, "capabilities": []})
    learned_repositories = repo_learning.get("learned_repositories") or []
    existing = {
        (str(item.get("provider_platform_id") or ""), str(item.get("capability_id") or "")): item
        for item in registry.get("capabilities", [])
    }

    assets: list[dict[str, Any]] = []
    synced = 0
    for repo in learned_repositories:
        repo_id = str(repo.get("repo_id") or "")
        full_name = str(repo.get("full_name") or repo.get("name") or "")
        if not repo_id or not full_name:
            continue
        repo_slug = _slug(full_name)
        repo_dir = ASSET_ROOT / repo_slug
        repo_dir.mkdir(parents=True, exist_ok=True)
        topics = repo.get("topics") or []
        sampled_files = repo.get("sampled_files") or []
        experiment_plan = repo.get("experiment_plan") or {}
        for capability_id in repo.get("capabilities") or []:
            capability_key = str(capability_id or "").strip()
            if not capability_key:
                continue
            provider_platform_id = f"github-learning:{repo_id}"
            asset_path = repo_dir / f"{_slug(capability_key)}.json"
            asset_payload = {
                "updated_at": _utc(),
                "source": "github_learning",
                "provider_platform_id": provider_platform_id,
                "repo_id": repo_id,
                "repo_full_name": full_name,
                "repo_local_path": repo.get("local_path"),
                "capability_id": capability_key,
                "keywords": _keywords(capability_key, {**repo, "topics": topics}),
                "sampled_files": sampled_files[:12],
                "key_files": (repo.get("key_files") or [])[:12],
                "architecture_summary": repo.get("architecture_summary") or "",
                "experiment_plan": experiment_plan,
                "distillation_status": distillation.get("status"),
                "adopted": bool(distillation.get("adopted", False)),
            }
            _save_json(asset_path, asset_payload)
            assets.append({
                "repo_id": repo_id,
                "repo_full_name": full_name,
                "capability_id": capability_key,
                "asset_path": str(asset_path),
            })
            reg_key = (provider_platform_id, capability_key)
            registry_entry = {
                "provider_platform_id": provider_platform_id,
                "provider_name": full_name,
                "workspace": repo.get("local_path"),
                "registered_at": _utc(),
                "version": 1,
                "capability_id": capability_key,
                "entrypoint": str(asset_path),
                "keywords": _keywords(capability_key, {**repo, "topics": topics}),
                "source": "github_learning",
                "repo_id": repo_id,
            }
            current = existing.get(reg_key)
            if current is None:
                registry.setdefault("capabilities", []).append(registry_entry)
                existing[reg_key] = registry_entry
                synced += 1
            else:
                current.update(registry_entry)

    registry["updated_at"] = _utc()
    registry["capabilities"] = sorted(
        registry.get("capabilities", []),
        key=lambda item: (
            str(item.get("capability_id") or ""),
            str(item.get("provider_platform_id") or ""),
        ),
    )
    _save_json(REGISTRY, registry)

    payload = {
        "updated_at": _utc(),
        "status": "ready" if assets else "idle",
        "learned_repository_count": len(learned_repositories),
        "asset_count": len(assets),
        "synced_registry_count": synced,
        "assets": assets[:40],
    }
    _save_json(LIBRARY, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(refresh_github_capability_library(), ensure_ascii=False, indent=2))
