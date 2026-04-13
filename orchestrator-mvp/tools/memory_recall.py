from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.memory_objects import recall_memory_objects, status_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recall MetaForge memory objects by query and filters.")
    parser.add_argument("query", nargs="*", default=[])
    parser.add_argument("--workspace", default="")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--type", dest="memory_type", action="append", default=[])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--include-candidates", action="store_true")
    parser.add_argument("--pack", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = " ".join(args.query).strip()
    if args.status:
        payload = status_report()
    else:
        payload = recall_memory_objects(
            query,
            workspace=args.workspace or None,
            tags=args.tag,
            memory_types=args.memory_type,
            limit=args.limit,
            include_candidates=args.include_candidates,
        )
        if args.pack:
            payload = payload.get("memory_pack", {})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
