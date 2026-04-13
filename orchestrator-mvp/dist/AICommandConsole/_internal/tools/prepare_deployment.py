from __future__ import annotations

import json
import shutil
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / 'templates' / 'deploy'


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Prepare deployment starter files in a workspace if missing.')
    parser.add_argument('workspace')
    args = parser.parse_args()
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    written = []
    mapping = {
        'docker-compose.app.yml': workspace / 'docker-compose.app.yml',
        'github-actions-deploy-template.yml': workspace / '.github' / 'workflows' / 'deploy-template.yml',
    }
    for name, target in mapping.items():
        source = TEMPLATE_DIR / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            written.append(str(target))
    print(json.dumps({'workspace': str(workspace), 'written_files': written}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
