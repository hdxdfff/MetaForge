from __future__ import annotations

import json
import sqlite3
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from json_store import read_json, read_jsonl_tail
from local_mind_paths import ROOT, resolve_local
from model_client import OllamaClient


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


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


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

                create index if not exists idx_vector_items_model
                  on vector_items(embedding_model);
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

    def embed_missing(self, client: OllamaClient, *, limit: int = 100, min_importance: float = 0.0) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                select memory_id, memory_type, content, importance, confidence, metadata_json
                from memory_items
                where length(trim(content)) > 0 and importance >= ?
                order by
                  case memory_type
                    when 'semantic' then 0
                    when 'procedural' then 1
                    when 'preference' then 2
                    else 3
                  end,
                  importance desc,
                  updated_at desc
                limit 1000
                """,
                (min_importance,),
            ).fetchall()
        with self.connect_vector() as vector_connection:
            existing = {
                str(row["memory_id"]): str(row["content_hash"])
                for row in vector_connection.execute(
                    "select memory_id, content_hash from vector_items where embedding_model = ?",
                    (client.embedding_model,),
                ).fetchall()
            }
        embedded = 0
        skipped = 0
        failures: list[dict[str, str]] = []
        for row in rows:
            memory_id = str(row["memory_id"])
            text = str(row["content"])
            digest = content_hash(text)
            if existing.get(memory_id) == digest:
                skipped += 1
                continue
            try:
                vector = client.embed(text)
            except Exception as exc:
                failures.append({"memory_id": memory_id, "error": str(exc)})
                continue
            if not vector:
                failures.append({"memory_id": memory_id, "error": "empty embedding"})
                continue
            with self.connect_vector() as vector_connection:
                vector_connection.execute(
                    """
                    insert into vector_items (
                      memory_id, embedding_model, embedding_json, content_hash, updated_at
                    )
                    values (?, ?, ?, ?, ?)
                    on conflict(memory_id) do update set
                      embedding_model = excluded.embedding_model,
                      embedding_json = excluded.embedding_json,
                      content_hash = excluded.content_hash,
                      updated_at = excluded.updated_at
                    """,
                    (memory_id, client.embedding_model, json.dumps(vector), digest, now_iso()),
                )
            embedded += 1
            if embedded >= limit:
                break
        return {
            "embedding_model": client.embedding_model,
            "embedded": embedded,
            "skipped": skipped,
            "failures": failures,
        }

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

    def search_vector(
        self,
        query: str,
        client: OllamaClient,
        *,
        top_k: int = 8,
        memory_types: set[str] | None = None,
    ) -> list[MemoryHit]:
        self.initialize()
        query_vector = client.embed(query)
        if not query_vector:
            return self.search(query, top_k=top_k, memory_types=memory_types)
        lexical_hits = {hit.memory_id: hit for hit in self.search(query, top_k=50, memory_types=memory_types)}
        with self.connect_vector() as vector_connection:
            vector_rows = vector_connection.execute(
                """
                select memory_id, embedding_json
                from vector_items
                where embedding_model = ?
                """,
                (client.embedding_model,),
            ).fetchall()
        if not vector_rows:
            return self.search(query, top_k=top_k, memory_types=memory_types)
        memory_ids = [str(row["memory_id"]) for row in vector_rows]
        placeholders = ",".join("?" for _ in memory_ids)
        with self.connect() as connection:
            memory_rows = connection.execute(
                f"""
                select memory_id, memory_type, content, importance, confidence, verified, metadata_json
                from memory_items
                where memory_id in ({placeholders})
                """,
                memory_ids,
            ).fetchall()
        memory_by_id = {str(row["memory_id"]): row for row in memory_rows}
        hits: list[MemoryHit] = []
        for vector_row in vector_rows:
            memory_id = str(vector_row["memory_id"])
            row = memory_by_id.get(memory_id)
            if row is None:
                continue
            memory_type = str(row["memory_type"])
            if memory_types and memory_type not in memory_types:
                continue
            vector = json.loads(vector_row["embedding_json"] or "[]")
            vector_score = cosine_similarity(query_vector, [float(value) for value in vector])
            lexical_score = lexical_hits.get(memory_id).score if memory_id in lexical_hits else 0.0
            score = vector_score * 0.75 + lexical_score * 0.25
            metadata = json.loads(row["metadata_json"] or "{}")
            hits.append(
                MemoryHit(
                    memory_id=memory_id,
                    memory_type=memory_type,
                    content=str(row["content"]),
                    score=score,
                    metadata={**metadata, "verified": bool(row["verified"]), "vector_score": vector_score, "lexical_score": lexical_score},
                )
            )
        if not hits:
            return self.search(query, top_k=top_k, memory_types=memory_types)
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
            "vectors": self.vector_stats(),
        }

    def vector_stats(self) -> dict[str, Any]:
        self.initialize()
        with self.connect_vector() as connection:
            rows = connection.execute(
                """
                select embedding_model, count(*) as count
                from vector_items
                group by embedding_model
                order by embedding_model
                """
            ).fetchall()
        return {str(row["embedding_model"]): int(row["count"]) for row in rows}


def main() -> None:
    import argparse
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true", help="Initialize SQLite stores and sync JSON/JSONL memories.")
    parser.add_argument("--embed-missing", action="store_true", help="Generate embeddings for memory items missing vectors.")
    parser.add_argument("--search", default=None, help="Search memories with lexical scoring.")
    parser.add_argument("--vector", action="store_true", help="Use vector search with lexical fallback for --search.")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    with (ROOT / "config" / "local_mind.yaml").open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    store = MemoryStore(config)
    if args.sync:
        print(json.dumps({"synced": store.sync_from_files(), "stats": store.stats()}, indent=2, ensure_ascii=False))
        return
    if args.embed_missing:
        store.sync_from_files()
        client = OllamaClient(config)
        print(json.dumps({"embedding": store.embed_missing(client, limit=args.limit), "stats": store.stats()}, indent=2, ensure_ascii=False))
        return
    if args.search:
        store.sync_from_files()
        if args.vector:
            client = OllamaClient(config)
            hits = [hit.as_context_item() for hit in store.search_vector(args.search, client)]
        else:
            hits = [hit.as_context_item() for hit in store.search(args.search)]
        print(json.dumps(hits, indent=2, ensure_ascii=False))
        return
    store.initialize()
    print(json.dumps(store.stats(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
