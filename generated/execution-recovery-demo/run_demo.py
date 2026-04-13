from __future__ import annotations

import json
import sys


def hello() -> str:
    return "hello from execution recovery"


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        print("SELF_TEST_OK")
        return 0
    payload = {"status": "ok", "message": hello(), "args": sys.argv[1:]}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
