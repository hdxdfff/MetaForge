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
    parser = argparse.ArgumentParser(description='Evaluate a generated system workspace against its template manifest.')
    parser.add_argument('workspace')
    parser.add_argument('template_id')
    args = parser.parse_args()
    workspace = Path(args.workspace)
    template = TEMPLATES / args.template_id / 'template.json'
    manifest = json.loads(template.read_text(encoding='utf-8'))
    checks = []
    missing = []
    for rel in manifest.get('required_paths', []):
        ok = (workspace / rel).exists()
        checks.append({'path': rel, 'ok': ok})
        if not ok:
            missing.append(rel)
    result = {
        'workspace': str(workspace),
        'template_id': args.template_id,
        'ok': not missing,
        'checks': checks,
        'missing': missing,
    }
    append_trace('evaluator', 'check generated workspace against template', f"evaluate {args.template_id}", f"ok={result['ok']} missing={len(missing)}", 'fix missing paths if needed', worker='cheap-worker', data={'workspace': str(workspace), 'template_id': args.template_id})
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
