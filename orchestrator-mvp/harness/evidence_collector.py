from __future__ import annotations

import shutil
from pathlib import Path

from tools.io_utils import atomic_write_json


class EvidenceCollector:
    def __init__(self, project_root: Path, run_dir: Path) -> None:
        self.project_root = project_root
        self.run_dir = run_dir
        self.evidence_dir = run_dir / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def collect_toyos_evidence(self) -> dict[str, str]:
        target = self.project_root.parent / "generated" / "toy-os-demo"
        mapping = {
            target / "build-report.json": self.evidence_dir / "build-report.json",
            target / "build" / "generic-qemu-smoke-report.json": self.evidence_dir / "qemu-smoke-report.json",
            target / "build" / "qemu-debug.log": self.evidence_dir / "qemu-output.txt",
        }
        copied: dict[str, str] = {}
        missing: list[str] = []
        for src, dst in mapping.items():
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied[str(src)] = str(dst)
            else:
                missing.append(str(src))
        summary = {"copied": copied, "missing": missing}
        atomic_write_json(self.evidence_dir / "evidence-summary.json", summary)
        return copied

