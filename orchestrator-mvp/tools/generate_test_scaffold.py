from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Generate a lightweight local test scaffold plan.')
    parser.add_argument('workspace')
    args = parser.parse_args()
    workspace = Path(args.workspace)
    files = []
    actions = []
    if (workspace / 'requirements.txt').exists() or list(workspace.glob('*.py')) or (workspace / 'app').exists():
        files.append(str(workspace / 'tests' / 'test_smoke.py'))
        actions.extend(['add pytest smoke coverage', 'validate python compile and JSON syntax'])
    if (workspace / 'package.json').exists():
        files.append(str(workspace / 'tests' / 'app.smoke.test.js'))
        actions.extend(['add npm smoke test', 'run node syntax checks'])
    if (workspace / 'Makefile').exists():
        actions.append('add make-based smoke or regression target')
    print(json.dumps({'workspace': str(workspace), 'suggested_test_files': files, 'actions': actions}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
