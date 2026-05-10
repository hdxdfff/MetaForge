from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import yaml

from consolidation import run_consolidation
from context_builder import build_context_packet
from json_store import read_json
from local_mind_paths import ROOT
from memory_manager import MemoryManager, now_iso
from model_client import OllamaClient
from preference_manager import handle_model_candidates
from router import should_escalate, should_use_think
from task_queue import TaskQueue
from tool_executor import ToolExecutor
from verifier import Verifier


def load_config() -> dict[str, Any]:
    with (ROOT / "config" / "local_mind.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class LocalMindDaemon:
    def __init__(self) -> None:
        self.config = load_config()
        self.memory = MemoryManager(self.config)
        self.queue = TaskQueue()
        self.executor = ToolExecutor()
        self.verifier = Verifier()
        self.model = OllamaClient(self.config)

    def heartbeat(self) -> None:
        queue_size = len(self.queue.read().get("tasks", []))
        state = self.memory.update_runtime_state(
            {
                "status": "running",
                "daemon_running": True,
                "last_heartbeat_at": now_iso(),
                "task_queue_size": queue_size,
                "last_error": None,
            }
        )
        self.memory.append_event(
            "heartbeat",
            "Local Mind daemon heartbeat",
            {"task_queue_size": queue_size, "status": state.get("status")},
            importance=0.2,
        )

    def health(self) -> dict[str, Any]:
        ollama = self.model.health()
        return {"status": "ok" if ollama.get("ok") else "degraded", "ollama": ollama}

    def should_call_model(self, state: dict[str, Any]) -> bool:
        if self.queue.select_next() is None:
            return False
        last_tick = parse_time(state.get("last_model_tick_at"))
        if last_tick is None:
            return True
        interval = int(self.config["runtime"].get("model_tick_interval_seconds", 300))
        return datetime.now(timezone.utc).astimezone() - last_tick >= timedelta(seconds=interval)

    def process_task(self, task: dict[str, Any]) -> None:
        state = read_json(ROOT / "data" / "runtime_state.json", {})
        recent = self.memory.recent_events()
        health = self.health()
        memories = self.memory.retrieve_relevant(task, embedding_client=self.model if health["status"] == "ok" else None)
        context = build_context_packet(task, state, recent, memories)
        context_hash = "sha256:" + hashlib.sha256(context.encode("utf-8")).hexdigest()
        if health["status"] != "ok":
            fallback = {
                "state_understanding": "Ollama is not available; using deterministic low-risk bootstrap action.",
                "memory_used": [],
                "proposed_actions": [
                    {
                        "type": "summarize",
                        "target": "reports/local_mind_status.md",
                        "args": {},
                        "risk_level": "low",
                        "reason": "Generate status evidence without model availability.",
                        "success_criteria": task.get("success_criteria", []),
                    }
                ],
                "should_escalate_to_cloud_model": False,
                "memory_write_candidates": [],
                "stop_reason": "fallback_no_ollama",
            }
            proposal = fallback
        else:
            proposal = self.model.chat_json(context, think=should_use_think(task))
        if should_escalate(task, proposal):
            self.queue.update_status(task["task_id"], "needs_user_review", notes="proposal requested escalation or high-risk action")
            return
        max_actions = int(self.config.get("safety", {}).get("max_actions_per_tick", 3))
        results = []
        for action in proposal.get("proposed_actions", [])[:max_actions]:
            result = self.executor.execute(action)
            verified = self.verifier.verify(action, result)
            results.append({"action": action, "result": result, "verified": verified})
        decision = {
            "decision_id": f"dec_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}",
            "timestamp": now_iso(),
            "task_id": task.get("task_id"),
            "context_hash": context_hash,
            "model": self.config["model"]["chat_model"],
            "proposal": proposal,
            "executor_results": results,
            "committed_to_state": self.verifier.all_success_criteria_met(task, results),
        }
        self.memory.append_decision(decision)
        preference_result = handle_model_candidates(
            proposal.get("memory_write_candidates", []),
            source_ref=decision["decision_id"],
        )
        self.memory.append_event(
            "task_processed",
            f"Processed task {task.get('task_id')}",
            {
                "decision_id": decision["decision_id"],
                "committed_to_state": decision["committed_to_state"],
                "preference_candidates": preference_result,
            },
            importance=0.7 if decision["committed_to_state"] else 0.5,
            verified=decision["committed_to_state"],
        )
        if decision["committed_to_state"]:
            evidence = next((item["result"].get("target") for item in results if item["result"].get("target")), None)
            self.queue.update_status(task["task_id"], "verified_success", evidence=evidence)
        else:
            self.queue.update_status(task["task_id"], "failed", notes="one or more proposed actions failed verification")
        self.memory.update_runtime_state({"last_model_tick_at": now_iso()})

    def maybe_consolidate(self) -> None:
        state = read_json(ROOT / "data" / "runtime_state.json", {})
        last = parse_time(state.get("last_consolidation_at"))
        interval = int(self.config["runtime"].get("consolidation_interval_hours", 24))
        if last is None or datetime.now(timezone.utc).astimezone() - last >= timedelta(hours=interval):
            result = run_consolidation()
            self.memory.append_event("consolidation", "Consolidated recent events", result, importance=0.6)
            self.memory.update_runtime_state({"last_consolidation_at": now_iso()})

    def maybe_maintain_embeddings(self, health: dict[str, Any]) -> None:
        if health["status"] != "ok":
            return
        state = read_json(ROOT / "data" / "runtime_state.json", {})
        last = parse_time(state.get("last_embedding_maintenance_at"))
        memory_config = self.config.get("memory", {})
        interval = int(memory_config.get("embedding_maintenance_interval_minutes", 30))
        if last is not None and datetime.now(timezone.utc).astimezone() - last < timedelta(minutes=interval):
            return
        result = self.memory.store.embed_missing(
            self.model,
            limit=int(memory_config.get("embedding_maintenance_limit", 24)),
            min_importance=float(memory_config.get("embedding_maintenance_min_importance", 0.0)),
        )
        self.memory.append_event(
            "embedding_maintenance",
            "Maintained memory embeddings",
            result,
            importance=0.4,
            verified=not result.get("failures"),
        )
        self.memory.update_runtime_state({"last_embedding_maintenance_at": now_iso()})

    def tick(self) -> None:
        self.heartbeat()
        state = read_json(ROOT / "data" / "runtime_state.json", {})
        health = self.health()
        if health["status"] != "ok":
            self.memory.append_event("health_degraded", "Ollama health check is degraded", health, importance=0.6, verified=False)
        if self.should_call_model(state):
            task = self.queue.select_next()
            if task:
                self.process_task(task)
        self.maybe_consolidate()
        self.maybe_maintain_embeddings(health)

    def run(self, once: bool = False) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:
                self.memory.update_runtime_state({"status": "degraded", "last_error": str(exc), "daemon_running": True})
                self.memory.append_event("daemon_error", str(exc), {"error": repr(exc)}, importance=0.8, verified=False)
                if once:
                    raise
            if once:
                return
            time.sleep(int(self.config["runtime"].get("tick_interval_seconds", 60)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    LocalMindDaemon().run(once=args.once)


if __name__ == "__main__":
    main()
