from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harness.evidence_collector import EvidenceCollector
from tools.io_utils import atomic_write_json


class Evaluator:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _run_command(self, command: str) -> tuple[bool, int | None, str]:
        completed = subprocess.run(
            command,
            cwd=self.project_root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        details = (
            f"exit_code={completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        return completed.returncode == 0, completed.returncode, details

    def _file_contains(self, file_path: Path, markers: list[str]) -> tuple[bool, str]:
        if not file_path.exists():
            return False, f"file_not_found: {file_path}"
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            return False, f"missing_markers={missing}"
        return True, "all_markers_present"

    def evaluate(self, contract: dict, run_dir: Path) -> Path:
        collector = EvidenceCollector(self.project_root, run_dir)
        checks_out: list[dict[str, str]] = []
        verdict = "pass"
        command_logs: dict[str, dict[str, str | int | None]] = {}
        for check in contract["acceptance_checks"]:
            ctype = check["type"]
            if ctype == "command_exit_code":
                ok, returncode, details = self._run_command(check["command"])
                expected = check.get("expected_exit_code", 0)
                ok = ok and returncode == expected
                command_logs[check["id"]] = {
                    "command": check["command"],
                    "returncode": returncode,
                    "expected_exit_code": expected,
                    "details": details,
                }
                if check["id"] in {"build_success", "qemu_smoke"}:
                    collector.collect_toyos_evidence()
                if check["id"] == "build_success":
                    build_report = self._load_json(run_dir / "evidence" / "build-report.json")
                    if not bool(build_report.get("build_success")):
                        ok = False
                        details = details + "\nassertion: build-report.json build_success != true"
                if check["id"] == "qemu_smoke":
                    qemu_report = self._load_json(run_dir / "evidence" / "qemu-smoke-report.json")
                    all_tests = qemu_report.get("tests") or []
                    qemu_ok = bool(all_tests) and all(bool(item.get("all_passed")) for item in all_tests)
                    if not qemu_ok:
                        ok = False
                        details = details + "\nassertion: qemu-smoke-report.json all_passed != true"
            elif ctype == "file_contains":
                ok, details = self._file_contains(self.project_root / check["file"], check["must_contain"])
            else:
                ok, details = False, f"unsupported_check_type={ctype}"
            checks_out.append(
                {
                    "id": check["id"],
                    "status": "pass" if ok else "fail",
                    "details": details,
                }
            )
            if not ok:
                verdict = "fail"

        evaluation = {
            "run_id": contract["run_id"],
            "evaluator_status": "completed",
            "verdict": verdict,
            "checks": checks_out,
            "command_logs": command_logs,
            "evidence_integrity": {},
            "final_reason": "All required checks passed with runtime evidence." if verdict == "pass" else "One or more acceptance checks failed.",
        }
        report_path = run_dir / "evaluation_report.json"
        atomic_write_json(report_path, evaluation)
        missing_files = [rel for rel in contract["required_evidence"] if not (run_dir / rel).exists()]
        evaluation["evidence_integrity"] = {
            "all_required_files_present": not missing_files,
            "missing_files": missing_files,
        }
        if missing_files:
            verdict = "fail"
            evaluation["verdict"] = verdict
            evaluation["final_reason"] = "One or more acceptance checks failed."
        atomic_write_json(report_path, evaluation)
        (run_dir / "logs" / "evaluator.log").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report_path
