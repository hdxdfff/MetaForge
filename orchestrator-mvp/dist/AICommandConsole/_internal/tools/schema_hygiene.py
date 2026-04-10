from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.factory_event_log import append_event
from tools.module_ownership import create_patch_submission, record_patch_artifacts, resolve_patch_submission
from tools.module_ownership_graph import build_module_ownership_graph

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE_ROOTS = [
    ROOT / "app",
    ROOT / "runtime",
    ROOT / "state",
    ROOT / "tools",
]
BUILD_SCRIPT = ROOT / "build-desktop.ps1"
DIST_ROOT = ROOT / "dist" / "AICommandConsole"
REPORT_PATH = DATA / "schema_hygiene_status.json"
JOURNAL_PATH = DATA / "schema_hygiene_journal.jsonl"
PATCH_RECORD_PATH = DATA / "schema_hygiene_patch_record.json"
SMOKE_REPORT_PATH = DATA / "schema_hygiene_smoke.json"
CORE_MESSAGES_PATH = DATA / "core_messages.json"
ALERT_MESSAGE_ID = "schema-hygiene-low-level-drift"
PATCH_NODE_ID = "schema-hygiene::low-level-drift"
PATCH_TEAM = "infrastructure_team"
SMOKE_PROBE_PATH = SOURCE_ROOTS[-1] / "_schema_hygiene_smoke_probe.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _save_core_messages(messages: list[dict[str, Any]]) -> None:
    _write_json(CORE_MESSAGES_PATH, messages)


def _summarize_findings(findings: list[dict[str, Any]], limit: int = 6) -> list[str]:
    summary: list[str] = []
    for item in findings[:limit]:
        summary.append(f"{item.get('rule')}@{Path(str(item.get('file') or '')).name}:{item.get('line')}")
    return summary


def _relative_path_text(path_text: str) -> str:
    path = Path(path_text)
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(path_text).replace("\\", "/")


def _module_name_from_relative_path(rel_path: str) -> str | None:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized.endswith(".py"):
        return None
    if normalized.startswith("tools/") or normalized.startswith("app/") or normalized.startswith("runtime/") or normalized.startswith("state/"):
        return normalized[:-3].replace("/", ".")
    return normalized[:-3].replace("/", ".")


def _patch_context_from_report(report: dict[str, Any]) -> dict[str, Any]:
    ownership = build_module_ownership_graph()
    module_index = {item.get("module"): item for item in ownership.get("modules", []) if item.get("module")}
    rel_paths = [_relative_path_text(path) for path in (report.get("fixed_files") or [])]
    module_focus: list[str] = []
    owner_teams: list[str] = []
    target_files: list[str] = []
    for rel_path in rel_paths:
        if not rel_path.endswith(".py"):
            continue
        target_files.append(rel_path)
        module_name = _module_name_from_relative_path(rel_path)
        if module_name and module_name not in module_focus:
            module_focus.append(module_name)
        if module_name:
            owner_team = (module_index.get(module_name) or {}).get("owner_team")
            if owner_team and owner_team not in owner_teams:
                owner_teams.append(owner_team)
    if not owner_teams:
        owner_teams = [PATCH_TEAM]
    if not module_focus:
        module_focus = ["tools.schema_hygiene"]
    return {
        "target_files": target_files,
        "module_focus": module_focus,
        "owner_teams": owner_teams,
    }


def _ensure_patch_submission(report: dict[str, Any], *, mode: str) -> dict[str, Any] | None:
    scan_count = int(report.get("scan_finding_count", report.get("finding_count", 0)) or 0)
    fixed_count = int(report.get("fixed_file_count", 0) or 0)
    if scan_count <= 0 and fixed_count <= 0:
        return None
    patch_context = _patch_context_from_report(report)
    title = "Schema hygiene low-level drift repair"
    reason = (
        f"Auto-repaired schema/projection drift during schema hygiene run (mode={mode}, "
        f"scan_findings={scan_count}, fixed_files={fixed_count})."
    )
    patch = create_patch_submission(
        task_id=None,
        node_id=PATCH_NODE_ID,
        title=title,
        team=PATCH_TEAM,
        owner_teams=patch_context["owner_teams"],
        module_focus=patch_context["module_focus"],
        reason=reason,
        repo_path=str(ROOT),
    )
    evidence = {
        "updated_at": report.get("updated_at") or _utc(),
        "report_path": str(REPORT_PATH),
        "journal_path": str(JOURNAL_PATH),
        "patch_record_path": str(PATCH_RECORD_PATH),
        "scan_finding_count": scan_count,
        "post_repair_finding_count": int(report.get("post_repair_finding_count", scan_count) or 0),
        "fixed_file_count": fixed_count,
        "fixed_files": list(report.get("fixed_files") or []),
        "rule_hits": dict(report.get("rule_hits") or {}),
        "mode": mode,
        "status": report.get("status"),
    }
    try:
        record_patch_artifacts(patch["patch_id"], artifacts=evidence)
    except Exception:
        pass
    return {
        "patch_id": patch.get("patch_id"),
        "status": patch.get("status"),
        "merge_status": patch.get("merge_status"),
        "review_gate": patch.get("review_gate"),
        "reason": patch.get("resolution"),
        "target_files": patch_context["target_files"],
        "module_focus": patch_context["module_focus"],
        "owner_teams": patch_context["owner_teams"],
        "artifacts": evidence,
    }


REPAIR_RULES: list[dict[str, Any]] = [
    {
        "name": "autonomy-confirmed-projection",
        "description": "Use canonical autonomy_is_confirmed helper instead of direct confirmed/stable_autonomy reads.",
        "patterns": [
            re.compile(r'autonomy\.get\("confirmed",\s*False\)'),
            re.compile(r"autonomy\.get\('confirmed',\s*False\)"),
            re.compile(r'autonomy\.get\("stable_autonomy"\)'),
            re.compile(r"autonomy\.get\('stable_autonomy'\)"),
            re.compile(r"\(\(autonomy\.get\('decision'\) or \{\}\)\.get\('stable_autonomy'\)\)"),
            re.compile(r'\(\(autonomy\.get\("decision"\) or \{\}\)\.get\("stable_autonomy"\)\)'),
        ],
        "replacement": "autonomy_is_confirmed(autonomy)",
        "import_line": "from tools.autonomy_state import autonomy_is_confirmed",
        "file_allowlist": None,
        "file_exclude": [ROOT / "tools" / "autonomy_state.py"],
    },
    {
        "name": "runtime-health-current-load",
        "description": "Treat runtime health as current unresolved load, not historical failure totals.",
        "patterns": [
            re.compile(r"healthy = len\(failed\) == 0 and len\(open_errors\) == 0"),
        ],
        "replacement": "healthy = len(active) == 0 and len(open_errors) == 0",
        "import_line": None,
        "file_allowlist": [ROOT / "tools" / "verification_engine.py"],
        "file_exclude": [],
    },
]


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for base in SOURCE_ROOTS:
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def _apply_rule_to_text(text: str, rule: dict[str, Any]) -> tuple[str, int]:
    replacements = 0
    for pattern in rule["patterns"]:
        text, count = pattern.subn(rule["replacement"], text)
        replacements += count
    return text, replacements


def _ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    lines = text.splitlines()
    insert_at = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from __future__ import"):
            insert_at = idx + 1
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = idx + 1
            continue
        if stripped == "":
            continue
        break
    lines.insert(insert_at, import_line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def scan_schema_drift() -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8-sig")
        for rule in REPAIR_RULES:
            allowlist = rule.get("file_allowlist")
            if allowlist is not None and path.resolve() not in {item.resolve() for item in allowlist}:
                continue
            excludes = rule.get("file_exclude") or []
            if excludes and path.resolve() in {item.resolve() for item in excludes}:
                continue
            for pattern in rule["patterns"]:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append({
                        "file": str(path),
                        "line": line,
                        "rule": rule["name"],
                        "description": rule["description"],
                    })
    return {
        "updated_at": _utc(),
        "finding_count": len(findings),
        "findings": findings[:50],
    }


def repair_schema_drift() -> dict[str, Any]:
    pre_scan = scan_schema_drift()
    findings = pre_scan.get("findings") or []
    changed_files: list[str] = []
    rule_hits: dict[str, int] = {}
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8-sig")
        original = text
        file_rules = []
        for rule in REPAIR_RULES:
            allowlist = rule.get("file_allowlist")
            if allowlist is not None and path.resolve() not in {item.resolve() for item in allowlist}:
                continue
            excludes = rule.get("file_exclude") or []
            if excludes and path.resolve() in {item.resolve() for item in excludes}:
                continue
            updated, count = _apply_rule_to_text(text, rule)
            if count:
                text = updated
                rule_hits[rule["name"]] = rule_hits.get(rule["name"], 0) + count
                if rule.get("import_line") and rule["import_line"] not in text:
                    text = _ensure_import(text, rule["import_line"])
                file_rules.append(rule["name"])
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed_files.append(str(path))
    bundle_rebuilt = False
    bundle_returncode = None
    if changed_files and BUILD_SCRIPT.exists():
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(BUILD_SCRIPT),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        bundle_returncode = completed.returncode
        bundle_rebuilt = completed.returncode == 0 and DIST_ROOT.exists()
    post_scan = scan_schema_drift()
    report = {
        "updated_at": _utc(),
        "scan_finding_count": int(pre_scan.get("finding_count", len(findings))),
        "scan_findings": findings[:50],
        "post_repair_finding_count": int(post_scan.get("finding_count", 0)),
        "post_repair_findings": post_scan.get("findings", [])[:50],
        "fixed_file_count": len(changed_files),
        "fixed_files": changed_files,
        "rule_hits": rule_hits,
        "bundle_rebuilt": bundle_rebuilt,
        "bundle_returncode": bundle_returncode,
        "status": "fixed"
        if changed_files and int(post_scan.get("finding_count", 0)) == 0
        else "attention"
        if int(post_scan.get("finding_count", 0)) > 0
        else "clean",
        "findings": findings[:50],
    }
    _write_json(REPORT_PATH, report)
    return report


def _update_alert_state(report: dict[str, Any], *, mode: str) -> dict[str, Any]:
    current_findings = int(report.get("post_repair_finding_count", report.get("finding_count", report.get("scan_finding_count", 0))) or 0)
    messages = _load_json(CORE_MESSAGES_PATH, [])
    existing = None
    for item in messages:
        if item.get("id") == ALERT_MESSAGE_ID:
            existing = item
            break
    alert_status = "open" if current_findings > 0 else "auto-resolved"
    if current_findings > 0:
        body_lines = [
            f"Schema hygiene run detected {current_findings} low-level drift item(s).",
            f"Mode: {mode}",
            f"Fixed files: {', '.join(report.get('fixed_files') or []) or 'none'}",
            f"Rules: {', '.join((report.get('rule_hits') or {}).keys()) or 'none'}",
            f"Findings: {', '.join(_summarize_findings(report.get('scan_findings') or [])) or 'none'}",
        ]
        message = {
            "id": ALERT_MESSAGE_ID,
            "created_at": (existing or {}).get("created_at") or report.get("updated_at") or _utc(),
            "updated_at": report.get("updated_at") or _utc(),
            "status": "open",
            "source": "schema_hygiene",
            "severity": "warning",
            "title": "Schema hygiene drift detected",
            "body": "\n".join(body_lines),
            "task_id": None,
            "step_id": "schema-hygiene",
            "repo_path": str(ROOT),
            "rule_hits": report.get("rule_hits") or {},
            "finding_count": current_findings,
            "fixed_file_count": int(report.get("fixed_file_count", 0) or 0),
            "updated_at": report.get("updated_at") or _utc(),
            "resolved_at": None,
            "resolution": None,
        }
        if existing is None:
            messages.append(message)
        else:
            existing.update(message)
        _save_core_messages(messages)
    elif existing is not None:
        existing["status"] = "auto-resolved"
        existing["updated_at"] = report.get("updated_at") or _utc()
        existing["resolved_at"] = report.get("updated_at") or _utc()
        existing["resolution"] = "Auto-resolved by schema hygiene after post-repair scan returned clean."
        _save_core_messages(messages)
    return {
        "message_id": ALERT_MESSAGE_ID if current_findings > 0 or existing is not None else None,
        "status": alert_status,
        "finding_count": current_findings,
    }


def _record_patch_history(report: dict[str, Any], *, mode: str, alert_state: dict[str, Any], patch_submission: dict[str, Any] | None) -> dict[str, Any]:
    record = {
        "record_id": f"schema_hygiene_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "updated_at": report.get("updated_at") or _utc(),
        "mode": mode,
        "status": report.get("status"),
        "scan_finding_count": int(report.get("scan_finding_count", report.get("finding_count", 0)) or 0),
        "post_repair_finding_count": int(report.get("post_repair_finding_count", report.get("finding_count", 0)) or 0),
        "fixed_file_count": int(report.get("fixed_file_count", 0) or 0),
        "fixed_files": list(report.get("fixed_files") or []),
        "bundle_rebuilt": bool(report.get("bundle_rebuilt")),
        "rule_hits": dict(report.get("rule_hits") or {}),
        "alert_state": alert_state,
        "patch_submission": patch_submission,
        "report_path": str(REPORT_PATH),
    }
    _append_jsonl(JOURNAL_PATH, record)
    history_payload = _load_json(PATCH_RECORD_PATH, {"updated_at": None, "records": []})
    history = list(history_payload.get("records") or [])
    history.append(record)
    history_payload.update(
        {
            "updated_at": record["updated_at"],
            "latest_record": record,
            "record_count": len(history),
            "records": history[-50:],
        }
    )
    _write_json(PATCH_RECORD_PATH, history_payload)
    return record


def _write_smoke_probe() -> Path:
    SMOKE_PROBE_PATH.write_text(
        "from __future__ import annotations\n\n\n"
        "def legacy_projection(autonomy: dict) -> bool:\n"
        "    return autonomy.get(\"confirmed\", False)\n",
        encoding="utf-8",
    )
    return SMOKE_PROBE_PATH


def run_schema_hygiene_smoke() -> dict[str, Any]:
    probe_path = None
    first_run: dict[str, Any] | None = None
    cleanup_resolution = "Synthetic schema hygiene smoke test completed; probe removed."
    rejected_patch: dict[str, Any] | None = None
    clean_run: dict[str, Any] | None = None
    try:
        probe_path = _write_smoke_probe()
        first_run = run_schema_hygiene(mode="full")
        patch_submission = first_run.get("patch_submission") or {}
        patch_id = patch_submission.get("patch_id")
        if patch_id:
            rejected_patch = resolve_patch_submission(patch_id, status="rejected", resolution=cleanup_resolution)
    finally:
        if probe_path and probe_path.exists():
            try:
                probe_path.unlink()
            except Exception:
                pass
    clean_run = run_schema_hygiene(mode="full")
    smoke_report = {
        "updated_at": _utc(),
        "probe_path": str(SMOKE_PROBE_PATH),
        "first_run": first_run,
        "rejected_patch": rejected_patch,
        "cleanup_resolution": cleanup_resolution,
        "cleanup_complete": not SMOKE_PROBE_PATH.exists(),
        "clean_run": clean_run,
        "status": "pass"
        if first_run
        and first_run.get("patch_submission")
        and rejected_patch
        and clean_run
        and int(clean_run.get("scan_finding_count", clean_run.get("finding_count", 0)) or 0) == 0
        else "attention",
    }
    _write_json(SMOKE_REPORT_PATH, smoke_report)
    append_event(
        "schema_hygiene.smoke",
        source="schema_hygiene",
        summary=f"schema hygiene smoke status={smoke_report['status']} probe={SMOKE_PROBE_PATH.name}",
        payload=smoke_report,
        refs={
            "smoke_report_path": str(SMOKE_REPORT_PATH),
            "report_path": str(REPORT_PATH),
            "journal_path": str(JOURNAL_PATH),
            "patch_record_path": str(PATCH_RECORD_PATH),
        },
        severity="warning" if smoke_report["status"] != "pass" else "info",
    )
    return smoke_report


def run_schema_hygiene(mode: str = "full") -> dict[str, Any]:
    if mode == "light":
        report = scan_schema_drift()
        report["status"] = "scanned" if report.get("finding_count", 0) == 0 else "attention"
        report["scan_finding_count"] = int(report.get("finding_count", 0) or 0)
        report["post_repair_finding_count"] = int(report.get("finding_count", 0) or 0)
        report["scan_findings"] = list(report.get("findings") or [])
        report["post_repair_findings"] = list(report.get("findings") or [])
        _write_json(REPORT_PATH, report)
    else:
        report = repair_schema_drift()
    alert_state = _update_alert_state(report, mode=mode)
    patch_submission = _ensure_patch_submission(report, mode=mode)
    patch_record = _record_patch_history(report, mode=mode, alert_state=alert_state, patch_submission=patch_submission)
    event_type = "schema_hygiene.clean"
    severity = "info"
    if alert_state.get("finding_count", 0) > 0:
        event_type = "schema_hygiene.repair" if report.get("status") == "fixed" else "schema_hygiene.alert"
        severity = "warning"
    append_event(
        event_type,
        source="schema_hygiene",
        summary=f"schema hygiene mode={mode} status={report.get('status')} findings={alert_state.get('finding_count', 0)}",
        payload={
            "mode": mode,
            "report": report,
            "alert_state": alert_state,
            "patch_submission": patch_submission,
            "patch_record_id": patch_record.get("record_id"),
        },
        refs={
            "report_path": str(REPORT_PATH),
            "journal_path": str(JOURNAL_PATH),
            "patch_record_path": str(PATCH_RECORD_PATH),
            "core_messages_path": str(CORE_MESSAGES_PATH),
        },
        severity=severity,
    )
    report["alert_state"] = alert_state
    report["patch_submission"] = patch_submission
    report["patch_record"] = patch_record
    return report


if __name__ == "__main__":
    print(json.dumps(run_schema_hygiene(), ensure_ascii=False, indent=2))
