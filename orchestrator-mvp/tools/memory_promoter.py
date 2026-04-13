from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.memory_objects import (
    bootstrap_memory_objects,
    auto_promote_candidates,
    harvest_memory_candidates,
    promote_candidate,
    register_candidate_from_object,
    status_report,
)


def _load_json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote memory candidates into the MetaForge object store.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap")
    sub.add_parser("harvest")
    p_auto = sub.add_parser("auto-promote")
    p_auto.add_argument("--min-confidence", type=float, default=None)
    p_auto.add_argument("--limit", type=int, default=None)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--input", required=True)

    p_promote = sub.add_parser("promote")
    p_promote.add_argument("--candidate-id")

    sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "bootstrap":
        payload = bootstrap_memory_objects()
    elif args.command == "harvest":
        payload = harvest_memory_candidates()
    elif args.command == "auto-promote":
        payload = auto_promote_candidates(min_confidence=args.min_confidence, limit=args.limit)
    elif args.command == "ingest":
        payload = register_candidate_from_object(_load_json(args.input))
    elif args.command == "promote":
        payload = promote_candidate(candidate_id=args.candidate_id)
    else:
        payload = status_report()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
