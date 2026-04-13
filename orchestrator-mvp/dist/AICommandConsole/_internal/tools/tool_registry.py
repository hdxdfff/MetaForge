from __future__ import annotations

import json
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


def route_tool(request: str) -> dict[str, Any]:
    query = (request or '').strip().lower()
    tools = list_tools()
    scored: list[dict[str, Any]] = []
    for tool in tools:
        keywords = [str(item).lower() for item in tool.get('keywords', [])]
        score = 0
        for keyword in keywords:
            if keyword and keyword in query:
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
    scored.sort(key=lambda item: (-item['score'], item['tool_id']))
    return {
        'request': request,
        'selected': scored[0] if scored else None,
        'candidates': scored[:5],
        'tool_count': len(tools),
    }


if __name__ == '__main__':
    print(json.dumps(load_registry(), ensure_ascii=False, indent=2))
