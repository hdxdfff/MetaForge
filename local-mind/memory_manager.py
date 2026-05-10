from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from json_store import append_jsonl, read_json, read_jsonl_tail, write_json
from local_mind_paths import ROOT, resolve_local
from memory_store import MemoryStore


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class MemoryManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        memory = config.get("memory", {})
        self.event_log = resolve_local(memory.get("event_log", "data/event_log.jsonl"))
        self.decision_ledger = resolve_local(memory.get("decision_ledger", "data/decision_ledger.jsonl"))
        self.max_recent_events = int(memory.get("max_recent_events", 20))
        self.store = MemoryStore(config)
        self.last_sync_counts = self.store.sync_from_files()

    def append_event(
        self,
        event_type: str,
        summary: str,
        raw_observation: dict[str, Any] | None = None,
        importance: float = 0.3,
        verified: bool = True,
        source: str = "daemon",
    ) -> dict[str, Any]:
        record = {
            "event_id": f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}",
            "timestamp": now_iso(),
            "source": source,
            "event_type": event_type,
            "summary": summary,
            "raw_observation": raw_observation or {},
            "importance": importance,
            "verified": verified,
            "memory_candidate": importance >= float(self.config.get("memory", {}).get("consolidation_min_importance", 0.65)),
        }
        append_jsonl(self.event_log, record)
        self.store.upsert_memory(
            memory_id=record["event_id"],
            memory_type="event",
            content=summary,
            source="event_log",
            source_ref=str(self.event_log),
            importance=importance,
            confidence=1.0 if verified else 0.4,
            verified=verified,
            metadata=record,
        )
        return record

    def append_decision(self, record: dict[str, Any]) -> None:
        append_jsonl(self.decision_ledger, record)

    def recent_events(self) -> list[dict[str, Any]]:
        return read_jsonl_tail(self.event_log, self.max_recent_events)

    def retrieve_relevant(self, task: dict[str, Any], embedding_client: Any | None = None) -> list[dict[str, Any]]:
        semantic = read_json(ROOT / "data" / "semantic_memory.json", {"memories": []}).get("memories", [])
        procedures = read_json(ROOT / "data" / "procedural_memory.json", {"procedures": []}).get("procedures", [])
        title = task.get("title", "").lower()
        memories: list[dict[str, Any]] = []
        for item in semantic:
            content = item.get("content", "").lower()
            if "proposal" in content or any(token in content for token in title.split()):
                memories.append({"type": "semantic", **item})
        for item in procedures:
            trigger = item.get("trigger", "").lower()
            if "status" in title or any(token in trigger for token in title.split()):
                memories.append({"type": "procedural", **item})
        top_k = int(self.config.get("memory", {}).get("retrieve_top_k", 8))
        if embedding_client is not None:
            try:
                sqlite_hits = [hit.as_context_item() for hit in self.store.search_vector(task.get("title", ""), embedding_client, top_k=top_k)]
            except Exception:
                sqlite_hits = [hit.as_context_item() for hit in self.store.search(task.get("title", ""), top_k=top_k)]
        else:
            sqlite_hits = [hit.as_context_item() for hit in self.store.search(task.get("title", ""), top_k=top_k)]
        seen = {item.get("memory_id") or item.get("procedure_id") for item in memories}
        for hit in sqlite_hits:
            if hit.get("memory_id") not in seen:
                memories.append(hit)
                seen.add(hit.get("memory_id"))
        return memories[:top_k]

    def update_runtime_state(self, updates: dict[str, Any]) -> dict[str, Any]:
        path = ROOT / "data" / "runtime_state.json"
        state = read_json(path, {})
        state.update(updates)
        write_json(path, state)
        return state
