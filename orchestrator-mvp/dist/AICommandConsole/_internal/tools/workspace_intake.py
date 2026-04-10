from __future__ import annotations

import json
from pathlib import Path

SIGNALS = {
    'python': ['requirements.txt', 'pyproject.toml', 'setup.py'],
    'node': ['package.json'],
    'docker': ['docker-compose.yml', 'docker-compose.yaml', 'Dockerfile'],
    'c-cpp': ['Makefile', 'CMakeLists.txt'],
    'java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
    'dotnet': ['*.sln', '*.csproj'],
}


def detect_stack(path: Path) -> list[str]:
    found: list[str] = []
    names = {item.name for item in path.iterdir()} if path.exists() else set()
    for label, patterns in SIGNALS.items():
        for pattern in patterns:
            if '*' in pattern:
                if list(path.glob(pattern)):
                    found.append(label)
                    break
            elif pattern in names:
                found.append(label)
                break
    return sorted(set(found))


def build_summary(path: Path) -> dict:
    top = []
    for item in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:20]:
        top.append({
            'name': item.name,
            'kind': 'dir' if item.is_dir() else 'file',
        })
    notes = []
    if (path / 'README.md').exists():
        notes.append('README present')
    if (path / '.git').exists():
        notes.append('git repo present')
    return {
        'path': str(path),
        'exists': path.exists(),
        'stack': detect_stack(path),
        'top_entries': top,
        'notes': notes,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Scan a workspace and summarize likely tooling.')
    parser.add_argument('workspace')
    args = parser.parse_args()
    workspace = Path(args.workspace)
    print(json.dumps(build_summary(workspace), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
