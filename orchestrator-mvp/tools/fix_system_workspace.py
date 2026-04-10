from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates' / 'systems'


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Repair missing required paths in a generated workspace.')
    parser.add_argument('workspace')
    parser.add_argument('template_id')
    args = parser.parse_args()
    workspace = Path(args.workspace)
    manifest = json.loads((TEMPLATES / args.template_id / 'template.json').read_text(encoding='utf-8'))
    repaired = []
    for rel in manifest.get('required_paths', []):
        target = workspace / rel
        if target.exists():
            continue
        if '.' in target.name:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix.lower() == '.md':
                target.write_text(f'# {target.stem}\n', encoding='utf-8')
            else:
                target.write_text('', encoding='utf-8')
        else:
            target.mkdir(parents=True, exist_ok=True)
        repaired.append(rel)
    append_trace('fixer', 'repair missing required paths', f"fix {args.template_id}", f"repaired={len(repaired)}", 're-run evaluator', worker='cheap-worker', data={'workspace': str(workspace), 'template_id': args.template_id})
    print(json.dumps({'workspace': str(workspace), 'template_id': args.template_id, 'repaired': repaired}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
