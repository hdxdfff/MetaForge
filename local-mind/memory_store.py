from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from json_store import read_json, read_jsonl_tail
from local_mind_paths import ROOT, resolve_local


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(slots=True)
class MemoryHit:
    memory_id: str
    memory_type: str
    content: str
    score: float
    metadata: dict[str, Any]

    def as_context_item(self) -> dict[str, Any]:
        return {
            "type": self.memory_type,
            "memory_id": self.memory_id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
        }


def tokenize(text: str) -> set[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in text)
    return {token for token in normalized.split() if len(token) > 1}


class MemoryStore:
    def __init__(self, config: dict[str, Any]):
        memory = config.get("memory", {})
        self.db_path = resolve_local(memory.get("sqlite_db", "data/memory.sqlite"))
        self.vector_db_path = resolve_local(memory.get("vector_index", "vector_index/memory_index.sqlite"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def connect_vector(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.vector_db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                create table if not exists memory_items (
                  memory_id text primary key,
                  memory_type text not null,
                  content text not null,
                  source text not null,
                  source_ref text,
                  importance real not null default 0,
                  confidence real not null default 0,
                  verified integer not null default 0,
                  metadata_json text not null default '{}',
                  created_at text not null,
                  updated_at text not null
                );

                create table if not exists memory_sources (
                  source_id text primary key,
                  source_type text not null,
                  source_path text,
                  source_ref text,
                  observed_at text,
                  metadata_json text not null default '{}'
                );

                create index if not exists idx_memory_items_type
                  on memory_items(memory_type);
                create index if not exists idx_memory_items_importance
                  on memory_items(importance desc);
                create index if not exists idx_memory_items_updated
                  on memory_items(updated_at desc);
                """
            )
        with self.connect_vector() as connection:
            connection.executescript(
                """
                create table if not exists vector_items (
                  memory_id text primary key,
                  embedding_model text,
                  embedding_json text,
                  content_hash text,
                  updated_at text not null
                );
                """
            )

    def upsert_memory(
        self,
        *,
        memory_id: str,
        memory_type: str,
        content: str,
        source: str,
        source_ref: str | None = None,
        importance: float = 0,
        confidence: float = 0,
        verified: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        stamp = now_iso()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute(
                """
                insert into memory_items (
                  memory_id, memory_type, content, source, source_ref,
                  importance, confidence, verified, metadata_json, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(memory_id) do update set
                  memory_type = excluded.memory_type,
                  content = excluded.content,
                  source = excluded.source,
                  source_ref = excluded.source_ref,
                  importance = excluded.importance,
                  confidence = excluded.confidence,
                  verified = excluded.verified,
                  metadata_json = excluded.metadata_json,
                  updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    memory_type,
                    content,
                    source,
                    source_ref,
                    importance,
                    confidence,
                    1 if verified else 0,
                    metadata_json,
                    stamp,
                    stamp,
                ),
            )

    def sync_from_files(self) -> dict[str, int]:
        self.initialize()
        counts = {"event": 0, "semantic": 0, "procedural": 0, "preference": 0}
        for event in read_jsonl_tail(ROOT / "data" / "event_log.jsonl", 5000):
            event_id = event.get("event_id")
            if not event_id:
                continue
            self.upsert_memory(
                memory_id=event_id,
                memory_type="event",
                content=event.get("summary", ""),
                source="event_log",
                source_ref="data/event_log.jsonl",
                importance=float(event.get("importance", 0)),
                confidence=1.0 if event.get("verified") else 0.4,
                verified=bool(event.get("verified")),
                metadata=event,
            )
            counts["event"] += 1
        semantic = read_json(ROOT / "data" / "semantic_memory.json", {"memories": []}).get("memories", [])
        for item in semantic:
            memory_id = item.get("memory_id")
            if not memory_id:
                continue
            self.upsert_memory(
                memory_id=memory_id,
                memory_type="semantic",
                content=item.get("content", ""),
                source="semantic_memory",
                source_ref="data/semantic_memory.json",
                importance=float(item.get("importance", item.get("confidence", 0.7))),
                confidence=float(item.get("confidence", 0.7)),
                verified=bool(item.get("last_verified_at")),
                metadata=item,
            )
            counts["semantic"] += 1
        procedures = read_json(ROOT / "data" / "procedural_memory.json", {"procedures": []}).get("procedures", [])
        for item in procedures:
            procedure_id = item.get("procedure_id")
            if not procedure_id:
                continue
            content = "\n".join([item.get("name", ""), item.get("trigger", ""), *item.get("steps", [])])
            self.upsert_memory(
                memory_id=procedure_id,
                memory_type="procedural",
                content=content,
                source="procedural_memory",
                source_ref="data/procedural_memory.json",
                importance=min(1.0, 0.4 + float(item.get("verified_success_count", 0)) * 0.1),
                confidence=min(1.0, 0.5 + float(item.get("verified_success_count", 0)) * 0.1),
                verified=int(item.get("verified_success_count", 0)) > 0,
                metadata=item,
            )
            counts["procedural"] += 1
        preferences = read_json(ROOT / "data" / "preference_memory.json", {"preferences": []}).get("preferences", [])
        for item in preferences:
            memory_id = item.get("memory_id") or item.get("preference_id")
            if not memory_id:
                continue
            self.upsert_memory(
                memory_id=memory_id,
                memory_type="preference",
                content=item.get("content", ""),
                source="preference_memory",
                source_ref="data/preference_memory.json",
                importance=float(item.get("importance", 0.8)),
                confidence=float(item.get("confidence", 0.8)),
                verified=bool(item.get("user_confirmed", False)),
                metadata=item,
            )
            counts["preference"] += 1
        return counts

    def search(self, query: str, *, top_k: int = 8, memory_types: set[str] | None = None) -> list[MemoryHit]:
        self.initialize()
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                select memory_id, memory_type, content, importance, confidence, verified, metadata_json
                from memory_items
                order by importance desc, updated_at desc
                limit 500
                """
            ).fetchall()
        hits: list[MemoryHit] = []
        for row in rows:
            memory_type = str(row["memory_type"])
            if memory_types and memory_type not in memory_types:
                continue
            content = str(row["content"])
            content_tokens = tokenize(content)
            overlap = len(query_tokens & content_tokens)
            if overlap == 0 and memory_type not in {"semantic", "procedural", "preference"}:
                continue
            lexical = overlap / max(len(query_tokens), 1)
            score = lexical + float(row["importance"]) * 0.25 + float(row["confidence"]) * 0.15
            metadata = json.loads(row["metadata_json"] or "{}")
            hits.append(
                MemoryHit(
                    memory_id=str(row["memory_id"]),
                    memory_type=memory_type,
                    content=content,
                    score=score,
                    metadata={**metadata, "verified": bool(row["verified"])},
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    def stats(self) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                select memory_type, count(*) as count
                from memory_items
                group by memory_type
                order by memory_type
                """
            ).fetchall()
        return {
            "sqlite_db": str(self.db_path),
            "vector_index": str(self.vector_db_path),
            "counts": {str(row["memory_type"]): int(row["count"]) for row in rows},
        }


def main() -> None:
    import argparse
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true", help="Initialize SQLite stores and sync JSON/JSONL memories.")
    parser.add_argument("--search", default=None, help="Search memories with lexical scoring.")
    args = parser.parse_args()

    with (ROOT / "config" / "local_mind.yaml").open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    store = MemoryStore(config)
    if args.sync:
        print(json.dumps({"synced": store.sync_from_files(), "stats": store.stats()}, indent=2, ensure_ascii=False))
        return
    if args.search:
        store.sync_from_files()
        hits = [hit.as_context_item() for hit in store.search(args.search)]
        print(json.dumps(hits, indent=2, ensure_ascii=False))
        return
    store.initialize()
    print(json.dumps(store.stats(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
