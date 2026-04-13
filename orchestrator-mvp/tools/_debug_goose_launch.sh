#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import os
import shutil
import subprocess

print("PATH=", os.environ.get("PATH"))
print("which_goose=", shutil.which("goose"))
for label, args in [
    ("direct", ["goose", "info"]),
    ("absolute", ["/usr/local/bin/goose", "info"]),
]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
        print(label, "rc=", completed.returncode)
        print(label, "stdout=", completed.stdout.strip())
        print(label, "stderr=", completed.stderr.strip())
    except Exception as exc:
        print(label, "exc=", type(exc).__name__, str(exc))
PY
