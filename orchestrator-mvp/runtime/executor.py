from __future__ import annotations

from tools.brain_loop import run_once


def execute_tick() -> dict:
    return run_once()
