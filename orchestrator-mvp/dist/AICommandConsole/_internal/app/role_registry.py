from __future__ import annotations

import json
from pathlib import Path


class RoleRegistry:
    def __init__(self, policy_path: Path) -> None:
        with policy_path.open("r", encoding="utf-8") as handle:
            self.matrix = json.load(handle)

    def assert_allowed(self, role: str, action: str) -> None:
        allowed = set(self.matrix[role]["allow"])
        denied = set(self.matrix[role]["deny"])
        if action in denied or action not in allowed:
            raise PermissionError(f"role={role} action={action} is not allowed")
