docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<"PY"
import json
from tools.quality_system import run_quality
print(json.dumps(run_quality(), ensure_ascii=False))
PY'
