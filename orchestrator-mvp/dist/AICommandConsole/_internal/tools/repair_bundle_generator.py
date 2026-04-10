from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERATED = ROOT / "generated"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _find_queue_item(queue: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for section in ("open_items", "in_progress_items", "done_items", "failed_items"):
        for item in queue.get(section) or []:
            if isinstance(item, dict) and str(item.get("id") or "") == item_id:
                return item
    return None


def run_repair_bundle_generator(
    item_id: str,
    *,
    output_root: Path | None = None,
    source_queue_path: Path | None = None,
) -> dict[str, Any]:
    output_root = output_root or (GENERATED / "repairs")
    source_queue_path = source_queue_path or (DATA / "self_improvement_queue.json")
    queue = _load_json(source_queue_path, {})
    item = _find_queue_item(queue if isinstance(queue, dict) else {}, item_id)
    if item is None:
        raise ValueError(f"Repair item not found: {item_id}")

    bundle_dir = output_root / item_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    if source_queue_path.exists():
        shutil.copy2(source_queue_path, bundle_dir / source_queue_path.name)
    manifest = {
        "version": 1,
        "bundle_id": item_id,
        "created_at": _utc(),
        "source_queue": str(source_queue_path),
        "bundle_root": str(bundle_dir),
        "item": item,
    }
    atomic_write_json(bundle_dir / "repair_bundle_manifest.json", manifest)
    atomic_write_json(bundle_dir / "repair_request.json", item)
    atomic_write_json(
        bundle_dir / "verification_plan.json",
        {
            "verification_plan": item.get("verification_plan") or [],
            "expected_fix_signal": item.get("expected_fix_signal"),
            "goal": item.get("goal"),
        },
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a repair evidence bundle from a self-improvement queue item.")
    parser.add_argument("item_id", help="Repair item id.")
    parser.add_argument("--output-root", default=str(GENERATED / "repairs"))
    parser.add_argument("--source-queue", default=str(DATA / "self_improvement_queue.json"))
    args = parser.parse_args()
    payload = run_repair_bundle_generator(
        args.item_id,
        output_root=Path(args.output_root),
        source_queue_path=Path(args.source_queue),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
