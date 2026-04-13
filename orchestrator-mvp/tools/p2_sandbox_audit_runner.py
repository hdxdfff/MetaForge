from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the P2 sandbox control-plane summary.")
    parser.add_argument("--input-md", required=True)
    parser.add_argument("--control-json", required=True)
    parser.add_argument(
        "--industrial-operations",
        default=str(Path(__file__).resolve().parent.parent / "data" / "industrial_operations.json"),
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    input_md = Path(args.input_md)
    control_json = Path(args.control_json)
    industrial_operations = Path(args.industrial_operations)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown = _read_text(input_md)
    control = _read_json(control_json)
    industrial = _read_json(industrial_operations)

    section_present = "## P2 Sandbox" in markdown
    allow_p2_sandbox = bool((((control.get("sandbox_controls") or {}).get("allow_p2_sandbox"))))
    industrial_allow = bool((((industrial.get("budget_control") or {}).get("gates") or {}).get("allow_p2_sandbox")))
    budget_pool = "P2" if section_present else "unknown"
    sandbox_lane = "p2_low_risk" if section_present else "unknown"
    if not section_present:
        status = "fail"
    elif allow_p2_sandbox and industrial_allow:
        status = "pass"
    else:
        status = "blocked"
    gate_state = "sandbox_open" if (allow_p2_sandbox and industrial_allow) else "sandbox_closed"

    report = {
        "status": status,
        "updated_at": utc_iso(),
        "checks": {
            "markdown_section_present": section_present,
            "allow_p2_sandbox": allow_p2_sandbox,
            "industrial_allow_p2_sandbox": industrial_allow,
            "budget_pool": budget_pool,
            "sandbox_lane": sandbox_lane,
        },
        "target_files": [
            str(input_md),
            str(control_json),
            str(industrial_operations),
        ],
        "smallest_gap": "" if status == "pass" else (
            "The summary markdown is missing the P2 sandbox section."
            if not section_present
            else "The sandbox gate is intentionally closed by the industrial operations budget."
        ),
        "patch_plan": [
            "Keep the P2 sandbox section in the summary markdown.",
            "Keep allow_p2_sandbox aligned with the industrial operations gate.",
            "Refresh the control-plane summary after any budget change.",
        ],
        "validation_commands": [
            f'Get-Content "{input_md}"',
            f'python D:\\codex\\orchestrator-mvp\\tools\\autonomy_control_plane.py',
        ],
        "residual_risk": "Sandbox lane remains intentionally narrow and budgeted.",
    }

    report_json = output_dir / "p2-sandbox-audit-report.json"
    report_md = output_dir / "p2-sandbox-audit-report.md"
    manifest = output_dir / "artifact_manifest.json"

    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(
        "\n".join(
            [
                "# P2 Sandbox Audit Report",
                "",
                "## Target Files",
                f"- {input_md}",
                f"- {control_json}",
                "",
                "## Smallest Gap",
                report["smallest_gap"] or "None",
                "",
                "## Gate State",
                f"- control_json_allow_p2_sandbox: {allow_p2_sandbox}",
                f"- industrial_allow_p2_sandbox: {industrial_allow}",
                f"- budget_gate: {gate_state}",
                "",
                "## Patch Plan",
                *[f"- {item}" for item in report["patch_plan"]],
                "",
                "## Validation Commands",
                *[f"- {item}" for item in report["validation_commands"]],
                "",
                "## Residual Risk",
                report["residual_risk"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "artifact_id": "p2-sandbox-audit-report",
                "type": "audit",
                "version": "1.0.0",
                "buildable": True,
                "runnable": True,
                "test_passed": status == "pass",
                "reproducible": True,
                "artifact_path": str(output_dir),
                "entrypoint": "p2-sandbox-audit-runner.py",
                "evidence": ["p2-sandbox-audit-report.json", "p2-sandbox-audit-report.md"],
                "updated_at": report["updated_at"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
