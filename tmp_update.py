from pathlib import Path
path = Path(r'D:\codex\orchestrator-mvp\tools\decision_engine.py')
text = path.read_text(encoding='utf-8')
old = "import json\nfrom datetime import datetime, timezone, timedelta\nfrom pathlib import Path\nfrom typing import Any\n\nfrom tools.goal_registry import create_goal, list_goals\n"
new = "import json\nimport sys\nfrom datetime import datetime, timezone, timedelta\nfrom pathlib import Path\nfrom typing import Any\n\nROOT = Path(__file__).resolve().parent.parent\nsys.path.insert(0, str(ROOT))\n\nfrom tools.goal_registry import create_goal, list_goals\n"
text = text.replace(old, new, 1)
text = text.replace("ROOT = Path(__file__).resolve().parent.parent\nDATA = ROOT / \"data\"\n", "DATA = ROOT / \"data\"\n", 1)
path.write_text(text, encoding='utf-8')
print('ok')
