from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

COMMANDS = {
    'mysql': ['mysql', '--version'],
    'mysqldump': ['mysqldump', '--version'],
    'mysqladmin': ['mysqladmin', '--version'],
    'psql': ['psql', '--version'],
    'gsql': ['gsql', '--version'],
    'docker': ['docker', '--version'],
    'java': ['java', '--version'],
}

WORKSPACES = [
    Path(r'D:\?????'),
    Path(r'D:\codex\orchestrator-mvp'),
]


def check_command(name: str, command: list[str]) -> dict:
    exe = shutil.which(command[0])
    if not exe:
        return {'available': False, 'path': None, 'version': None}
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=8)
        output = (completed.stdout or completed.stderr or '').strip().splitlines()
        version = output[0] if output else ''
        return {'available': completed.returncode == 0 or bool(version), 'path': exe, 'version': version}
    except Exception as exc:
        return {'available': True, 'path': exe, 'version': f'error: {exc}'}


def scan_workspace(path: Path) -> dict:
    info = {
        'path': str(path),
        'exists': path.exists(),
        'sql_files': 0,
        'docs': [],
        'runtime_hints': [],
    }
    if not path.exists():
        return info
    info['sql_files'] = len(list(path.rglob('*.sql')))
    for pattern in ['README.md', '*.pdf', '*.docx', '*.md']:
        for item in list(path.glob(pattern))[:5]:
            info['docs'].append(item.name)
    names = {item.name.lower() for item in path.iterdir()}
    if 'docker-compose.yml' in names or 'docker-compose.yaml' in names:
        info['runtime_hints'].append('docker-compose')
    if any(name.endswith('.sql') for name in names):
        info['runtime_hints'].append('sql-files-present')
    if any('opengauss' in name.lower() for name in names):
        info['runtime_hints'].append('openGauss-materials')
    return info


def main() -> int:
    payload = {
        'commands': {name: check_command(name, command) for name, command in COMMANDS.items()},
        'workspaces': [scan_workspace(path) for path in WORKSPACES],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
