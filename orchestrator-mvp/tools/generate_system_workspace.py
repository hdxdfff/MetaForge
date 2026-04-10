from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates' / 'systems'
WORKSPACE_ROOT = ROOT / 'workspace'


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return value.strip('-') or 'project'


def copy_template(src: Path, dst: Path, project_name: str) -> None:
    for item in src.rglob('*'):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.name == 'template.json':
            shutil.copyfile(item, target)
            continue
        content = item.read_text(encoding='utf-8').replace('{{project_name}}', project_name)
        target.write_text(content, encoding='utf-8')


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Generate an isolated system workspace from a template.')
    parser.add_argument('template_id')
    parser.add_argument('project_name')
    args = parser.parse_args()
    src = TEMPLATES / args.template_id
    if not src.exists():
        raise SystemExit(f'Unknown template: {args.template_id}')
    slug = slugify(args.project_name)
    dst = WORKSPACE_ROOT / slug
    dst.mkdir(parents=True, exist_ok=True)
    copy_template(src, dst, args.project_name)
    manifest = json.loads((src / 'template.json').read_text(encoding='utf-8'))
    result = {
        'template_id': args.template_id,
        'project_name': args.project_name,
        'project_slug': slug,
        'workspace': str(dst),
        'required_paths': manifest.get('required_paths', []),
    }
    append_trace('generator', 'create isolated system from template', f"generate {args.template_id}", f"workspace={dst}", 'run system evaluator', worker='cheap-worker', data={'template_id': args.template_id, 'workspace': str(dst)})
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
