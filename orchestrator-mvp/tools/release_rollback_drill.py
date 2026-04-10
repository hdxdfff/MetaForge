from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.artifact_audit import validate_release_payload
from tools.execution_trace import append_trace
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
GENERATED = ROOT / "generated" / "release-rollback-drill"
TOYOS_ROOT = ROOT.parent / "generated" / "toy-os-demo"
RELEASE_RECORDS_PATH = DATA / "release_records.json"
OUTPUT_PATH = DATA / "release_rollback_drill.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def main() -> int:
    started_at = datetime.now(timezone.utc)
    release_records = _load_json(RELEASE_RECORDS_PATH, [])
    if not isinstance(release_records, list):
        release_records = []

    evidence_dir = GENERATED / started_at.strftime("%Y%m%dT%H%M%SZ")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    dummy_record = {
        "id": f"rollback-drill-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": _utc(),
        "repo_path": str(TOYOS_ROOT),
        "branch": "rollback-drill",
        "artifacts": [
            "artifact_manifest.json",
            "build-report.json",
            "build/generic-qemu-smoke-report.json",
            "toyos-delivery-closure-report.md",
        ],
        "blockers": [],
        "status": "candidate",
        "notes": "Synthetic rollback drill using current ToyOS delivery artifacts.",
    }
    validation = validate_release_payload(dummy_record["repo_path"], dummy_record["artifacts"])
    dummy_record["artifact_evidence"] = validation
    dummy_record["status"] = "archived" if validation.get("passed") else "blocked"
    dummy_record["archived_reason"] = "rollback-drill-complete" if validation.get("passed") else "rollback-drill-validation-failed"
    dummy_record["archived_at"] = _utc()

    evidence = {
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": _utc(),
        "source": "drill",
        "release_record_count": len(release_records),
        "dummy_record": dummy_record,
        "validation_passed": bool(validation.get("passed")),
        "rollback_time_minutes": round((datetime.now(timezone.utc) - started_at).total_seconds() / 60.0, 4),
        "evidence_dir": str(evidence_dir),
    }

    _write_json(OUTPUT_PATH, evidence)
    _write_json(evidence_dir / "rollback-drill.json", evidence)
    append_trace(
        "release-rollback-drill",
        "measure release rollback drill",
        "run release_rollback_drill.py",
        f"time_minutes={evidence['rollback_time_minutes']} validation={evidence['validation_passed']}",
        "measure failed release rollback time",
        worker="cheap-worker",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
