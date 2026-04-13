from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.model_router import ModelRouter
from app.models import StepSpec, TaskRecord, WorkerType


def test_model_router_uses_route_experience_bias(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.model_router.load_usage_snapshot",
        lambda: {"reasoning_allowed": True, "strong_allowed": True, "reasoning_pressure": 0.0, "strong_pressure": 0.0},
    )
    monkeypatch.setattr(
        "app.model_router.load_route_experience",
        lambda: {
            "executors": {
                "openhands_executor": {
                    "samples": 8,
                    "success_rate": 0.2,
                    "avg_latency_ms": 40000.0,
                    "avg_cost_units": 7.0,
                }
            }
        },
    )

    router = ModelRouter()
    step = StepSpec(title="Implement feature", worker=WorkerType.coder, instructions="Implement the patch safely.")
    task = TaskRecord(
        prompt="Implement feature",
        executor_id="openhands_executor",
        executor_route={"selected": {"executor_id": "openhands_executor"}},
        task_type="build_fix",
        verification_level="L2",
    )

    route = router.route_step(step, task=task)

    assert route.provider == "openai"
    assert "experience" in route.reason.lower() or "history" in route.reason.lower()
