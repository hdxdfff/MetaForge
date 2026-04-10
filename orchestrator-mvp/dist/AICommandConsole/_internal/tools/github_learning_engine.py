from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from app.config import settings

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPOS = DATA / "repos.json"
CONFIG = DATA / "github_learning_config.json"
SCAN = DATA / "github_learning_scan.json"
STATUS = DATA / "github_learning_status.json"
GIT_FALLBACKS = [
    r"D:\\codex\\tools\\mingit-2.53.0-64-bit\\cmd\\git.exe",
    r"C:\\Program Files\\Git\\cmd\\git.exe",
]


DEFAULT_CURATED_REPOS = [
    {
        "full_name": "OpenInterpreter/open-interpreter",
        "clone_url": "https://github.com/OpenInterpreter/open-interpreter.git",
        "html_url": "https://github.com/OpenInterpreter/open-interpreter",
        "description": "Natural language computer control agent.",
        "language": "Python",
        "topics": ["agent", "computer-use", "tool-executor", "llm"],
        "stars": 58000,
        "recent_commits": 48,
        "updated_days_ago": 10,
        "source": "curated-default",
    },
    {
        "full_name": "microsoft/autogen",
        "clone_url": "https://github.com/microsoft/autogen.git",
        "html_url": "https://github.com/microsoft/autogen",
        "description": "Multi-agent framework for autonomous systems.",
        "language": "Python",
        "topics": ["agent", "multi-agent", "orchestration", "llm"],
        "stars": 41000,
        "recent_commits": 60,
        "updated_days_ago": 7,
        "source": "curated-default",
    },
    {
        "full_name": "langchain-ai/langchain",
        "clone_url": "https://github.com/langchain-ai/langchain.git",
        "html_url": "https://github.com/langchain-ai/langchain",
        "description": "Composable LLM application framework.",
        "language": "Python",
        "topics": ["agent", "llm", "tools", "retrieval"],
        "stars": 103000,
        "recent_commits": 95,
        "updated_days_ago": 4,
        "source": "curated-default",
    },
    {
        "full_name": "crewAIInc/crewAI",
        "clone_url": "https://github.com/crewAIInc/crewAI.git",
        "html_url": "https://github.com/crewAIInc/crewAI",
        "description": "Collaborative AI agents framework.",
        "language": "Python",
        "topics": ["agent", "multi-agent", "workflow", "automation"],
        "stars": 32000,
        "recent_commits": 52,
        "updated_days_ago": 9,
        "source": "curated-default",
    },
    {
        "full_name": "ggerganov/llama.cpp",
        "clone_url": "https://github.com/ggerganov/llama.cpp.git",
        "html_url": "https://github.com/ggerganov/llama.cpp",
        "description": "Local LLM inference in portable C/C++.",
        "language": "C++",
        "topics": ["inference", "llm", "kv-cache", "quantization"],
        "stars": 77000,
        "recent_commits": 72,
        "updated_days_ago": 3,
        "source": "curated-default",
    },
    {
        "full_name": "vllm-project/vllm",
        "clone_url": "https://github.com/vllm-project/vllm.git",
        "html_url": "https://github.com/vllm-project/vllm",
        "description": "High-throughput LLM serving engine.",
        "language": "Python",
        "topics": ["inference", "llm", "serving", "scheduler"],
        "stars": 38000,
        "recent_commits": 88,
        "updated_days_ago": 5,
        "source": "curated-default",
    },
    {
        "full_name": "ray-project/ray",
        "clone_url": "https://github.com/ray-project/ray.git",
        "html_url": "https://github.com/ray-project/ray",
        "description": "Distributed compute runtime and scheduling.",
        "language": "Python",
        "topics": ["distributed-system", "scheduler", "runtime", "ml"],
        "stars": 36000,
        "recent_commits": 75,
        "updated_days_ago": 6,
        "source": "curated-default",
    },
    {
        "full_name": "dask/dask",
        "clone_url": "https://github.com/dask/dask.git",
        "html_url": "https://github.com/dask/dask",
        "description": "Parallel and distributed Python execution.",
        "language": "Python",
        "topics": ["distributed-system", "scheduler", "parallel", "data"],
        "stars": 13000,
        "recent_commits": 34,
        "updated_days_ago": 8,
        "source": "curated-default",
    },
    {
        "full_name": "mit-pdos/xv6-public",
        "clone_url": "https://github.com/mit-pdos/xv6-public.git",
        "html_url": "https://github.com/mit-pdos/xv6-public",
        "description": "Small Unix-like teaching kernel.",
        "language": "C",
        "topics": ["kernel", "os", "scheduler", "systems"],
        "stars": 7800,
        "recent_commits": 4,
        "updated_days_ago": 240,
        "source": "curated-default",
    },
    {
        "full_name": "Significant-Gravitas/AutoGPT",
        "clone_url": "https://github.com/Significant-Gravitas/AutoGPT.git",
        "html_url": "https://github.com/Significant-Gravitas/AutoGPT",
        "description": "Agent platform and classic agent runtime.",
        "language": "Python",
        "topics": ["agent", "llm", "automation", "workflow"],
        "stars": 170000,
        "recent_commits": 40,
        "updated_days_ago": 12,
        "source": "local-vendor",
        "local_path": r"D:\codex\agents\autogpt-classic\vendor\AutoGPT",
    },
]


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


def _repo_id(full_name: str) -> str:
    return f"gh-{hashlib.sha1(full_name.encode('utf-8')).hexdigest()[:10]}"


def _default_config() -> dict[str, Any]:
    return {
        "updated_at": _utc(),
        "enabled": True,
        "topics": settings.github_learning_topics,
        "languages": settings.github_learning_languages,
        "min_stars": settings.github_learning_min_stars,
        "max_candidates": settings.github_learning_scan_limit,
        "clone_root": settings.github_learning_clone_root,
        "curated_repos": DEFAULT_CURATED_REPOS,
        "live_scan": settings.github_learning_live_scan,
    }


def ensure_learning_config() -> dict[str, Any]:
    config = _load_json(CONFIG, {})
    defaults = _default_config()
    if not config:
        config = defaults
        _save_json(CONFIG, config)
        return config
    changed = False
    for key, value in defaults.items():
        if key == "curated_repos":
            existing = {str(item.get("full_name") or ""): item for item in config.get("curated_repos", []) if str(item.get("full_name") or "")}
            curated = config.setdefault("curated_repos", [])
            for item in value:
                full_name = str(item.get("full_name") or "")
                if not full_name:
                    continue
                current = existing.get(full_name)
                if current is None:
                    curated.append(item)
                    changed = True
                else:
                    for field, field_value in item.items():
                        if current.get(field) != field_value:
                            current[field] = field_value
                            changed = True
            continue
        if key not in config:
            config[key] = value
            changed = True
    if changed:
        config["updated_at"] = _utc()
        _save_json(CONFIG, config)
    return config


def _topic_bonus(candidate: dict[str, Any], topics: list[str], languages: list[str]) -> tuple[float, dict[str, Any]]:
    topic_hits = [topic for topic in candidate.get("topics", []) if topic in topics]
    language_hit = str(candidate.get("language") or "").lower() in {item.lower() for item in languages}
    bonus = min(len(topic_hits), 3) / 3
    if language_hit:
        bonus += 0.5
    return bonus, {"topic_hits": topic_hits, "language_hit": language_hit}


def _score_candidate(candidate: dict[str, Any], topics: list[str], languages: list[str]) -> dict[str, Any]:
    stars = float(candidate.get("stars", 0) or 0.0)
    recent_commits = float(candidate.get("recent_commits", 0) or 0.0)
    updated_days_ago = float(candidate.get("updated_days_ago", 365) or 365.0)
    recency = max(0.0, 1.0 - min(updated_days_ago, 365.0) / 365.0)
    relevance, relevance_meta = _topic_bonus(candidate, topics, languages)
    scored = dict(candidate)
    scored["score"] = round(stars * 0.4 + recent_commits * 0.2 + recency * 100 * 0.2 + relevance * 100 * 0.2, 4)
    scored["quality_gate"] = {
        "stars_ok": stars >= settings.github_learning_min_stars,
        "fresh_ok": updated_days_ago <= 120,
        "docs_hint": True,
        "tests_hint": True,
    }
    scored["relevance"] = relevance_meta
    return scored


def _live_search(config: dict[str, Any], topics: list[str], limit: int) -> list[dict[str, Any]]:
    if not config.get("live_scan"):
        return []
    token = settings.github_token
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for topic in topics[:4]:
        query = urllib.parse.quote(f"topic:{topic} sort:stars")
        url = f"https://api.github.com/search/repositories?q={query}&per_page={max(1, min(limit, 10))}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
        for item in payload.get("items", []) or []:
            full_name = str(item.get("full_name") or "")
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)
            updated_days_ago = 365.0
            pushed_at = str(item.get("pushed_at") or "")
            if pushed_at:
                try:
                    dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                    updated_days_ago = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
                except Exception:
                    updated_days_ago = 365.0
            results.append(
                {
                    "full_name": full_name,
                    "clone_url": item.get("clone_url"),
                    "html_url": item.get("html_url"),
                    "description": item.get("description") or "",
                    "language": item.get("language") or "",
                    "topics": item.get("topics") or [],
                    "stars": item.get("stargazers_count") or 0,
                    "recent_commits": 20,
                    "updated_days_ago": round(updated_days_ago, 2),
                    "source": "github-live",
                }
            )
    return results


def _merge_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        full_name = str(item.get("full_name") or "")
        if not full_name:
            continue
        current = merged.get(full_name)
        if current is None or float(item.get("score", 0.0) or 0.0) > float(current.get("score", 0.0) or 0.0):
            merged[full_name] = item
    return sorted(merged.values(), key=lambda entry: entry.get("score", 0.0), reverse=True)


def _clone_root(config: dict[str, Any]) -> Path:
    return Path(str(config.get("clone_root") or settings.github_learning_clone_root))


def _resolve_git() -> str | None:
    git = shutil.which("git")
    if git:
        return git
    for candidate in GIT_FALLBACKS:
        if Path(candidate).exists():
            return candidate
    return None


def _git_env(git_path: str) -> dict[str, str]:
    env = dict(os.environ)
    git_file = Path(git_path)
    root = git_file.parent.parent if git_file.parent.name == "cmd" else git_file.parent
    helper_dirs = [root / "mingw64" / "bin", root / "mingw64" / "libexec" / "git-core", root / "libexec" / "git-core"]
    extras = [str(item) for item in helper_dirs if item.exists()]
    if extras:
        env["PATH"] = os.pathsep.join(extras + [env.get("PATH", "")])
        env.setdefault("GIT_EXEC_PATH", extras[0])
    return env


def _candidate_local_path(config: dict[str, Any], full_name: str) -> Path:
    owner, repo = full_name.split("/", 1)
    return _clone_root(config) / f"{owner}-{repo}"


def _local_path_for_candidate(config: dict[str, Any], candidate: dict[str, Any]) -> Path:
    override = str(candidate.get("local_path") or "").strip()
    if override:
        return Path(override)
    return _candidate_local_path(config, str(candidate.get("full_name") or ""))


def _repo_is_ready(local_path: str | Path | None) -> bool:
    path = Path(str(local_path or '')).expanduser()
    if not path.exists() or not path.is_dir():
        return False
    if (path / '.git').exists():
        return True
    markers = ('README.md', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod')
    if any((path / marker).exists() for marker in markers):
        return True
    try:
        return any(path.iterdir())
    except Exception:
        return False


def _read_repos() -> list[dict[str, Any]]:
    repos = _load_json(REPOS, [])
    return repos if isinstance(repos, list) else []


def _write_repos(repos: list[dict[str, Any]]) -> None:
    _save_json(REPOS, repos)


def register_scan_candidates(scan: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    repos = _read_repos()
    existing_by_name = {
        str(((item.get("metadata") or {}).get("full_name") or item.get("name") or "")).lower(): item
        for item in repos
    }
    config = ensure_learning_config()
    candidates = scan.get("candidates") or []
    selected = candidates[: limit] if limit else candidates
    registered = 0
    for item in selected:
        full_name = str(item.get("full_name") or "")
        if not full_name:
            continue
        local_path = str(_local_path_for_candidate(config, item))
        payload = {
            "id": _repo_id(full_name),
            "name": full_name.split("/", 1)[1],
            "local_path": local_path,
            "default_branch": "main",
            "remotes": [{"name": "github", "url": item.get("clone_url"), "provider": "github"}],
            "metadata": {
                "learning_source": item.get("source"),
                "full_name": full_name,
                "stars": item.get("stars", 0),
                "topics": item.get("topics", []),
                "description": item.get("description", ""),
                "score": item.get("score", 0.0),
                "learning_status": "ready" if _repo_is_ready(local_path) else "candidate",
            },
            "last_push_at": None,
        }
        existing = existing_by_name.get(full_name.lower())
        if existing:
            existing.update(payload)
        else:
            repos.append(payload)
            registered += 1
    _write_repos(repos)
    return {"updated_at": _utc(), "registered_count": registered, "repo_count": len(repos)}


def scan_github_repositories(topics: list[str] | None = None, limit: int | None = None) -> dict[str, Any]:
    config = ensure_learning_config()
    chosen_topics = topics or config.get("topics") or settings.github_learning_topics
    chosen_languages = config.get("languages") or settings.github_learning_languages
    max_candidates = limit or int(config.get("max_candidates") or settings.github_learning_scan_limit)
    raw = list(config.get("curated_repos") or DEFAULT_CURATED_REPOS)
    raw.extend(_live_search(config, chosen_topics, max_candidates))
    filtered = [
        item
        for item in _merge_candidates([_score_candidate(item, chosen_topics, chosen_languages) for item in raw])
        if (item.get("quality_gate") or {}).get("stars_ok")
    ][:max_candidates]
    payload = {
        "updated_at": _utc(),
        "enabled": bool(config.get("enabled", True)),
        "topics": chosen_topics,
        "languages": chosen_languages,
        "live_scan": bool(config.get("live_scan")),
        "candidate_count": len(filtered),
        "candidates": filtered,
    }
    _save_json(SCAN, payload)
    registration = register_scan_candidates(payload)
    status = github_learning_status()
    status["scan"] = {
        "updated_at": payload["updated_at"],
        "candidate_count": payload["candidate_count"],
        "live_scan": payload["live_scan"],
        "registered_count": registration["registered_count"],
    }
    _save_json(STATUS, status)
    return payload


def clone_learning_target(full_name: str | None = None, limit: int = 1) -> dict[str, Any]:
    config = ensure_learning_config()
    scan = _load_json(SCAN, {})
    candidates = scan.get("candidates") or []
    if full_name:
        candidates = [item for item in candidates if str(item.get("full_name") or "").lower() == full_name.lower()]
    git = _resolve_git()
    if not git:
        payload = {"updated_at": _utc(), "status": "blocked", "reason": "git-not-found", "operations": []}
        _save_json(STATUS, {**github_learning_status(), "clone": payload})
        return payload
    root = _clone_root(config)
    root.mkdir(parents=True, exist_ok=True)
    operations = []
    for item in candidates[: max(1, limit)]:
        repo_name = str(item.get("full_name") or "")
        target = _local_path_for_candidate(config, item)
        if target.exists():
            command = [git, "-C", str(target), "pull", "--ff-only"]
            action = "pull"
        else:
            command = [git, "clone", str(item.get("clone_url") or ""), str(target)]
            action = "clone"
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False, env=_git_env(git))
            success = completed.returncode == 0
            output = (completed.stdout or completed.stderr or "").strip()[:1200]
        except Exception as exc:
            success = False
            output = str(exc)
        operations.append({"repo": repo_name, "action": action, "target": str(target), "success": success, "output": output})
    repos = _read_repos()
    for repo in repos:
        metadata = repo.setdefault("metadata", {})
        full_name_repo = str(metadata.get("full_name") or "")
        if any(item["repo"] == full_name_repo and item["success"] for item in operations):
            metadata["learning_status"] = "ready"
    _write_repos(repos)
    payload = {
        "updated_at": _utc(),
        "status": "completed" if operations and all(item["success"] for item in operations) else "partial",
        "operation_count": len(operations),
        "operations": operations,
    }
    _save_json(STATUS, {**github_learning_status(), "clone": payload})
    return payload


def github_learning_status() -> dict[str, Any]:
    config = ensure_learning_config()
    repos = _read_repos()
    managed = [item for item in repos if any(remote.get("provider") == "github" for remote in item.get("remotes", []))]
    ready = [item for item in managed if Path(str(item.get("local_path") or "")).exists()]
    candidates = [item for item in managed if not Path(str(item.get("local_path") or "")).exists()]
    scan = _load_json(SCAN, {})
    return {
        "updated_at": _utc(),
        "enabled": bool(config.get("enabled", True)),
        "topics": config.get("topics") or [],
        "languages": config.get("languages") or [],
        "managed_repo_count": len(managed),
        "ready_repo_count": len(ready),
        "candidate_repo_count": len(candidates),
        "scan_candidate_count": len(scan.get("candidates") or []),
        "top_candidates": [
            {
                "full_name": ((item.get("metadata") or {}).get("full_name")) or item.get("name"),
                "local_path": item.get("local_path"),
                "score": (item.get("metadata") or {}).get("score", 0.0),
                "learning_status": (item.get("metadata") or {}).get("learning_status", "candidate"),
            }
            for item in managed[:8]
        ],
    }
