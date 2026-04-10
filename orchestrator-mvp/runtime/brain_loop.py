from __future__ import annotations

import argparse
import json
import time

from runtime.executor import execute_tick


def loop_forever(interval: int = 60) -> int:
    while True:
        result = execute_tick()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resident runtime brain loop")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(execute_tick(), ensure_ascii=False, indent=2))
        return 0
    return loop_forever(interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
