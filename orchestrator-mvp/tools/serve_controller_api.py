from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / ".venv" / "Lib" / "site-packages"
if SITE.exists():
    sys.path.insert(0, str(SITE))
sys.path.insert(0, str(ROOT))

import uvicorn


if __name__ == "__main__":
    host = os.environ.get("CONTROLLER_API_HOST", "0.0.0.0")
    port = int(os.environ.get("CONTROLLER_API_PORT", "8710"))
    uvicorn.run("app.controller_api:app", host=host, port=port, reload=False)

