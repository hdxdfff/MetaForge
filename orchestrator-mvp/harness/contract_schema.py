from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AcceptanceCheck:
    id: str
    type: str
    command: str | None = None
    expected_exit_code: int | None = None
    file: str | None = None
    must_contain: list[str] = field(default_factory=list)


@dataclass
class SprintContract:
    contract_version: str
    run_id: str
    goal_id: str
    product: str
    feature_name: str
    source_goal: str
    allowed_paths: list[str]
    forbidden_paths: list[str]
    max_files_to_change: int
    deliverables: list[str]
    definition_of_done: list[str]
    acceptance_checks: list[AcceptanceCheck]
    required_evidence: list[str]
    status: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SprintContract":
        scope = data["scope"]
        checks = [AcceptanceCheck(**item) for item in data["acceptance_checks"]]
        return cls(
            contract_version=data["contract_version"],
            run_id=data["run_id"],
            goal_id=data["goal_id"],
            product=data["product"],
            feature_name=data["feature_name"],
            source_goal=data["source_goal"],
            allowed_paths=scope["allowed_paths"],
            forbidden_paths=scope["forbidden_paths"],
            max_files_to_change=int(scope["max_files_to_change"]),
            deliverables=data["deliverables"],
            definition_of_done=data["definition_of_done"],
            acceptance_checks=checks,
            required_evidence=data["required_evidence"],
            status=data["status"],
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.feature_name.strip():
            errors.append("feature_name is empty")
        if not self.definition_of_done:
            errors.append("definition_of_done is empty")
        if not self.acceptance_checks:
            errors.append("acceptance_checks is empty")
        if not self.allowed_paths:
            errors.append("allowed_paths is empty")
        if self.max_files_to_change <= 0:
            errors.append("max_files_to_change must be > 0")
        if self.status != "approved_for_execution":
            errors.append("contract status must be approved_for_execution")
        return errors

