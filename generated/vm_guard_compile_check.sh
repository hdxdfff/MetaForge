python3 - <<'PY'
from pathlib import Path
for path in [
    '/srv/orchestrator-mvp/tools/ai_guard.py',
    '/srv/orchestrator-mvp/tools/evolution_control.py',
    '/srv/orchestrator-mvp/tools/meta_factory_control.py',
]:
    compile(Path(path).read_text(encoding='utf-8-sig'), path, 'exec')
print('ok')
PY
