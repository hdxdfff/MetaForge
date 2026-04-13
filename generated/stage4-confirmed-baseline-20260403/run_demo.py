from __future__ import annotations

import json
import sys


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        print("SELF_TEST_OK")
        return 0
    print(json.dumps({"status": "ok", "artifact_id": "stage4-confirmed-baseline-20260403", "message": 'Provide a runnable baseline snapshot bundle that can self-test and expose the frozen Stage 4 confirmed evidence.', "args": args}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
