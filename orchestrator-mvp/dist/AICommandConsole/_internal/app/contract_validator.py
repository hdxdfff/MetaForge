from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


class ContractValidator:
    def __init__(self, schema_dir: Path) -> None:
        self.schema_dir = schema_dir

    def _load_json(self, path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def validate(self, schema_name: str, payload: dict[str, Any]) -> None:
        schema_path = self.schema_dir / schema_name
        schema = self._load_json(schema_path)
        jsonschema.validate(instance=payload, schema=schema)
