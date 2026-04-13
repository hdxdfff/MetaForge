from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from app.config import settings
from tools.code_knowledge_graph import build_code_knowledge_graph
from tools.embedding_engine import embed_text, embedding_status
from tools.github_learning_engine import github_learning_status, scan_github_repositories

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
OUT = DATA / 'repo_learning_state.json'
CHUNKS = DATA / 'repo_learning_chunks.json'
REPOS = DATA / 'repos.json'

TEXT_EXTS = {'.py', '.md', '.json', '.toml', '.yml', '.yaml', '.ts', '.tsx', '.js', '.jsx', '.rs', '.go', '.c', '.cc', '.cpp', '.h'}
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', 'dist', 'build', 'target', '__pycache__', '.next'}
CAPABILITY_RULES = [
    ({'llama.cpp', 'vllm', 'llm', 'inference', 'quantization', 'kv-cache'}, ['local_llm_runner', 'token_streaming', 'kv_cache_manager']),
    ({'ray', 'dask', 'distributed', 'scheduler', 'cluster'}, ['distributed_executor', 'task_scheduler']),
    ({'agent', 'autogen', 'langchain', 'crewai', 'workflow', 'orchestration'}, ['agent_orchestration', 'tool_execution', 'workflow_planning']),
    ({'kernel', 'xv6', 'linux', 'os', 'boot'}, ['kernel_runtime', 'systems_debugging']),
    ({'compiler', 'llvm', 'rustc', 'parser'}, ['compiler_toolchain', 'code_analysis']),
]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _file_candidates(graph: dict[str, Any]) -> list[dict[str, Any]]:
    modules = graph.get('modules', [])
    ranked = sorted(modules, key=lambda item: (item.get('dependency_count', 0), item.get('dependent_count', 0)), reverse=True)
    return ranked[: settings.repo_learning_max_files]


def _read_text(path: Path) -> str:
    if not path.exists() or path.suffix.lower() not in TEXT_EXTS:
        return ''
    for encoding in ('utf-8', 'utf-8-sig'):
        try:
            return path.read_text(encoding=encoding)[: settings.repo_learning_max_file_chars]
        except Exception:
            continue
    return ''


def _managed_repos() -> list[dict[str, Any]]:
    repos = _load_json(REPOS, [])
    return repos if isinstance(repos, list) else []


def _iter_repo_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob('*'):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        files.append(path)
    return files


def _rank_repo_files(paths: list[Path]) -> list[Path]:
    def score(path: Path) -> tuple[int, int, int]:
        name = path.name.lower()
        priority = 0
        if name in {'readme.md', 'pyproject.toml', 'package.json', 'cargo.toml', 'go.mod', 'cmakelists.txt'}:
            priority += 5
        if 'example' in name or 'demo' in name or 'test' in name:
            priority += 2
        depth = -len(path.parts)
        try:
            size = path.stat().st_size
        except Exception:
            size = 0
        return (priority, size, depth)
    return sorted(paths, key=score, reverse=True)[: min(settings.repo_learning_max_files, 24)]


def _language_mix(paths: list[Path]) -> list[dict[str, Any]]:
    ext_map = {'.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript', '.js': 'JavaScript', '.jsx': 'JavaScript', '.rs': 'Rust', '.go': 'Go', '.c': 'C', '.cc': 'C++', '.cpp': 'C++', '.h': 'C/C++', '.md': 'Markdown'}
    counter = Counter(ext_map.get(path.suffix.lower(), path.suffix.lower()) for path in paths)
    return [{'language': language, 'files': count} for language, count in counter.most_common(6)]


def _key_files(repo_root: Path) -> list[str]:
    markers = ['README.md', 'pyproject.toml', 'requirements.txt', 'package.json', 'Cargo.toml', 'go.mod', 'CMakeLists.txt', 'Dockerfile']
    found = []
    for marker in markers:
        path = repo_root / marker
        if path.exists():
            found.append(str(path))
    return found


def _capabilities(repo: dict[str, Any], sampled_files: list[Path], readme_text: str) -> list[str]:
    metadata = repo.get('metadata') or {}
    tokens = set()
    for token in str(metadata.get('full_name') or repo.get('name') or '').replace('/', ' ').replace('-', ' ').replace('_', ' ').lower().split():
        tokens.add(token)
    for token in (metadata.get('topics') or []):
        tokens.add(str(token).lower())
    for path in sampled_files[:8]:
        for token in path.name.replace('.', ' ').replace('-', ' ').replace('_', ' ').lower().split():
            tokens.add(token)
    for token in readme_text[:1000].replace('/', ' ').replace('-', ' ').replace('_', ' ').lower().split():
        if len(token) > 2:
            tokens.add(token)
    capabilities: list[str] = []
    for keywords, produced in CAPABILITY_RULES:
        if tokens & keywords:
            for capability in produced:
                if capability not in capabilities:
                    capabilities.append(capability)
    return capabilities[:6]


def _experiment_plan(repo_root: Path) -> dict[str, Any]:
    commands = []
    if (repo_root / 'pyproject.toml').exists() or (repo_root / 'requirements.txt').exists():
        commands.extend(['python -m pytest', 'python demo.py'])
    if (repo_root / 'package.json').exists():
        commands.extend(['npm test', 'npm run dev'])
    if (repo_root / 'Cargo.toml').exists():
        commands.extend(['cargo test', 'cargo run'])
    if (repo_root / 'go.mod').exists():
        commands.extend(['go test ./...', 'go run .'])
    if (repo_root / 'CMakeLists.txt').exists():
        commands.extend(['cmake -S . -B build', 'cmake --build build'])
    return {
        'sandbox_required': True,
        'recommended_commands': commands[:4],
        'can_run_without_dependency_install': False,
    }


def _repo_summary(repo: dict[str, Any]) -> dict[str, Any] | None:
    repo_root = Path(str(repo.get('local_path') or ''))
    if not repo_root.exists() or not repo_root.is_dir():
        return None
    files = _iter_repo_files(repo_root)
    ranked = _rank_repo_files(files)
    readme_text = _read_text(repo_root / 'README.md')
    chunks = []
    for path in ranked:
        content = _read_text(path)
        if not content:
            continue
        chunks.append({
            'module': path.stem,
            'path': str(path),
            'layer': 'external_repo',
            'owner_team': 'github_learning',
            'summary': content[:400],
            'embedding': embed_text(content[:1000]),
            'repo_full_name': ((repo.get('metadata') or {}).get('full_name')) or repo.get('name'),
        })
    capabilities = _capabilities(repo, ranked, readme_text)
    return {
        'repo_id': repo.get('id'),
        'full_name': ((repo.get('metadata') or {}).get('full_name')) or repo.get('name'),
        'local_path': str(repo_root),
        'language_mix': _language_mix(files),
        'key_files': _key_files(repo_root),
        'sampled_files': [str(path) for path in ranked[:8]],
        'capabilities': capabilities,
        'architecture_summary': (readme_text[:600] if readme_text else ''),
        'experiment_plan': _experiment_plan(repo_root),
        'chunk_count': len(chunks),
        'chunks': chunks,
    }


def rebuild_repo_learning() -> dict[str, Any]:
    scan_github_repositories()
    graph = build_code_knowledge_graph()
    chunks = []
    for module in _file_candidates(graph):
        path = Path(module.get('path') or '')
        content = _read_text(path)
        if not content:
            continue
        chunks.append({
            'module': module.get('module'),
            'path': module.get('path'),
            'layer': module.get('layer'),
            'owner_team': module.get('owner_team'),
            'summary': content[:400],
            'embedding': embed_text(content[:1000]),
        })
    repos = _managed_repos()
    repo_summaries = []
    extracted_capabilities = []
    for repo in repos:
        summary = _repo_summary(repo)
        if not summary:
            continue
        repo_summaries.append({key: value for key, value in summary.items() if key != 'chunks'})
        chunks.extend(summary['chunks'])
        extracted_capabilities.extend(summary['capabilities'])
        metadata = repo.setdefault('metadata', {})
        metadata['learning_status'] = 'learned'
        metadata['learned_at'] = _utc()
        metadata['capabilities'] = summary['capabilities']
    _save_json(REPOS, repos)
    capabilities = sorted(set(extracted_capabilities))
    github_status = github_learning_status()
    payload = {
        'updated_at': _utc(),
        'embedding': embedding_status(),
        'graph_modules': graph.get('module_count', 0),
        'chunk_count': len(chunks),
        'top_modules': [
            {
                'module': item.get('module'),
                'layer': item.get('layer'),
                'owner_team': item.get('owner_team'),
                'path': item.get('path'),
            }
            for item in chunks[:12]
        ],
        'learned_repositories': repo_summaries,
        'learned_repository_count': len(repo_summaries),
        'extracted_capabilities': capabilities,
        'github_learning': github_status,
    }
    _save_json(CHUNKS, {'updated_at': payload['updated_at'], 'chunks': chunks, 'repositories': repo_summaries})
    _save_json(OUT, payload)
    return payload

