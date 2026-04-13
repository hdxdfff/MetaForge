from __future__ import annotations

import json
import re
from typing import Any

from .models import AuditCoderOutput, AuditReviewerOutput

AUDIT_TASK_TYPES = {
    "artifact_audit",
    "json_fix",
    "report_refresh",
    "doc_patch",
    "manifest_patch",
}


def is_audit_task(task_type: str | None) -> bool:
    return str(task_type or "").strip().lower() in AUDIT_TASK_TYPES


def _normalize_heading(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _split_items(text: str) -> list[str]:
    items: list[str] = []
    in_fence = False
    for line in str(text or "").splitlines():
        cleaned = line.strip().strip("*-").strip()
        if cleaned.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and not cleaned:
            continue
        cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
        cleaned = cleaned.strip("`").strip()
        if cleaned:
            items.append(cleaned)
    return items


def _collect_sections(text: str) -> dict[str, list[str]]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            sections: dict[str, list[str]] = {}
            for key, value in payload.items():
                normalized = _normalize_heading(str(key))
                if isinstance(value, list):
                    sections[normalized] = [str(item).strip() for item in value if str(item).strip()]
                elif value is None:
                    sections[normalized] = []
                else:
                    sections[normalized] = [str(value).strip()]
            return sections
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if heading:
            current = _normalize_heading(heading.group(1))
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections.setdefault(current, []).append(line.rstrip())
    return sections


def parse_audit_output(text: str, *, worker_name: str) -> AuditCoderOutput | AuditReviewerOutput:
    sections = _collect_sections(text)
    worker = str(worker_name or "").strip().lower()
    if worker == "reviewer":
        evidence_checked = _split_items("\n".join(sections.get("evidence_checked", [])))
        regression_risks = _split_items("\n".join(sections.get("regression_risks", [])))
        payload = {
            "verdict": "\n".join(sections.get("verdict", [])).strip(),
            "evidence_checked": evidence_checked,
            "validation_status": "\n".join(sections.get("validation_status", [])).strip(),
            "regression_risks": regression_risks,
            "follow_up_patch": "\n".join(sections.get("follow_up_patch", [])).strip(),
            "next_action": "\n".join(sections.get("next_action", [])).strip(),
        }
        return AuditReviewerOutput.model_validate(payload)
    payload = {
        "target_files": _split_items("\n".join(sections.get("target_files", []))),
        "smallest_gap": "\n".join(sections.get("smallest_gap", [])).strip(),
        "patch_plan": "\n".join(sections.get("patch_plan", [])).strip(),
        "validation_commands": _split_items("\n".join(sections.get("validation_commands", []))),
        "residual_risk": "\n".join(sections.get("residual_risk", [])).strip(),
    }
    return AuditCoderOutput.model_validate(payload)


def validate_audit_output(text: str, *, worker_name: str) -> tuple[bool, str]:
    try:
        parsed = parse_audit_output(text, worker_name=worker_name)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if isinstance(parsed, AuditReviewerOutput):
        if not parsed.verdict or not parsed.validation_status or not parsed.next_action:
            return False, "Reviewer audit output missing required structured sections."
        if not parsed.evidence_checked:
            return False, "Reviewer audit output missing evidence_checked items."
        return True, ""
    if not parsed.target_files or not parsed.patch_plan or not parsed.validation_commands:
        return False, "Coder audit output missing required structured sections."
    if not parsed.smallest_gap or not parsed.residual_risk:
        return False, "Coder audit output missing required narrative sections."
    return True, ""
