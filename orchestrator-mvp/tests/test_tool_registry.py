from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import tool_registry


def test_route_tool_avoids_partial_word_false_positive(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_registry,
        "list_tools",
        lambda: [
            {"tool_id": "git_status", "keywords": ["git"], "domain": "code", "provider": "git", "command": "git status"},
            {"tool_id": "sign_verify", "keywords": ["digital"], "domain": "security", "provider": "local", "command": "verify-signature"},
        ],
    )

    result = tool_registry.route_tool("Need digital signature verification for release artifact")

    assert result["selected"] is not None
    assert result["selected"]["tool_id"] == "sign_verify"


def test_route_tool_supports_phrase_keyword_whitespace(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_registry,
        "list_tools",
        lambda: [
            {"tool_id": "pytest_run", "keywords": ["unit test"], "domain": "code", "provider": "pytest", "command": "pytest"},
            {"tool_id": "git_status", "keywords": ["status"], "domain": "code", "provider": "git", "command": "git status"},
        ],
    )

    result = tool_registry.route_tool("please run unit    test for parser module")

    assert result["selected"] is not None
    assert result["selected"]["tool_id"] == "pytest_run"
