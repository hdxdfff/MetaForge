from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.artifact_audit import build_reality_dashboard


if __name__ == "__main__":
    print(json.dumps(build_reality_dashboard(write_outputs=True), ensure_ascii=False, indent=2))
