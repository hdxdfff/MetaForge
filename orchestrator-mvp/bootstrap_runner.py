from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE_PACKAGES = ROOT / '.venv' / 'Lib' / 'site-packages'

if SITE_PACKAGES.exists():
    sys.path.insert(0, str(SITE_PACKAGES))
sys.path.insert(0, str(ROOT))

if len(sys.argv) < 2:
    raise SystemExit('Usage: bootstrap_runner.py [-m module | script.py] [args...]')

if sys.argv[1] == '-m':
    if len(sys.argv) < 3:
        raise SystemExit('Missing module name after -m')
    module = sys.argv[2]
    sys.argv = [module, *sys.argv[3:]]
    runpy.run_module(module, run_name='__main__')
else:
    script = Path(sys.argv[1])
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name='__main__')
