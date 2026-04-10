from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / 'templates' / 'reports' / 'lab-report.md.tpl'


def bullet_lines(items: list[str]) -> str:
    if not items:
        return '- None'
    return '\n'.join(f'- {item}' for item in items)


def screenshot_lines(items: list[dict]) -> str:
    if not items:
        return '- No screenshots attached.'
    lines = []
    for item in items:
        path = item.get('path') or ''
        caption = item.get('caption') or Path(path).name or 'Screenshot'
        lines.append(f'- {caption}')
        lines.append(f'\n![{caption}]({path})\n')
    return '\n'.join(lines)


def render(payload: dict) -> str:
    template = TEMPLATE.read_text(encoding='utf-8')
    mappings = {
        'title': payload.get('title') or payload.get('experiment') or 'Lab Report',
        'date': payload.get('date') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'course': payload.get('course') or 'Unknown Course',
        'experiment': payload.get('experiment') or 'Unknown Experiment',
        'workspace': payload.get('workspace') or 'n/a',
        'objective': payload.get('objective') or 'Not provided.',
        'environment': bullet_lines(payload.get('environment') or []),
        'steps': bullet_lines(payload.get('steps') or []),
        'observations': bullet_lines(payload.get('observations') or []),
        'result': payload.get('result') or 'Not provided.',
        'screenshots': screenshot_lines(payload.get('screenshots') or []),
        'risks': bullet_lines(payload.get('risks') or []),
    }
    for key, value in mappings.items():
        template = template.replace('{{' + key + '}}', value)
    return template


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Generate a markdown lab report.')
    parser.add_argument('payload_json', help='Path to a JSON payload file')
    parser.add_argument('--out', required=True, help='Output markdown path')
    args = parser.parse_args()
    payload = json.loads(Path(args.payload_json).read_text(encoding='utf-8'))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(payload), encoding='utf-8')
    print(json.dumps({'ok': True, 'output_path': str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
