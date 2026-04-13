from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / 'data' / 'tool_registry.json'


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_registry() -> dict[str, Any]:
    return _load_json(REGISTRY, {'tools': []})


def list_tools() -> list[dict[str, Any]]:
    return load_registry().get('tools', [])


def _keyword_hit(query: str, keyword: str) -> bool:
    token = str(keyword or '').strip().lower()
    if not token:
        return False
    if token in query and not re.search(r"[a-z0-9]", token):
        return True
    pattern = re.escape(token).replace(r'\ ', r'\s+')
    return bool(re.search(rf'(?<![a-z0-9]){pattern}(?![a-z0-9])', query))


def route_tool(request: str) -> dict[str, Any]:
    query = (request or '').strip().lower()
    tools = list_tools()
    scored: list[dict[str, Any]] = []
    for tool in tools:
        keywords = [str(item).lower().strip() for item in tool.get('keywords', [])]
        score = 0
        for keyword in keywords:
            if _keyword_hit(query, keyword):
                score += 1
        if score > 0:
            scored.append(
                {
                    'tool_id': tool.get('tool_id'),
                    'domain': tool.get('domain'),
                    'provider': tool.get('provider'),
                    'command': tool.get('command'),
                    'score': score,
                    'keywords': tool.get('keywords', []),
                }
            )
    scored.sort(key=lambda item: (-item['score'], str(item.get('tool_id') or '')))
    return {
        'request': request,
        'selected': scored[0] if scored else None,
        'candidates': scored[:5],
        'tool_count': len(tools),
    }


if __name__ == '__main__':
    print(json.dumps(load_registry(), ensure_ascii=False, indent=2))
