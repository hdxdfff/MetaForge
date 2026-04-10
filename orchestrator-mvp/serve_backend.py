from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / ".venv" / "Lib" / "site-packages"
if SITE.exists():
    sys.path.insert(0, str(SITE))
sys.path.insert(0, str(ROOT))

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8788,
        reload=False,
        loop="asyncio",
        http="h11",
        lifespan="off",
        access_log=False,
        log_level="warning",
    )
