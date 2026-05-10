# Local Mind Kernel

WSL-friendly local continuous-memory kernel for `D:/codex`.

This is a guarded V0/V1 scaffold:

- Ollama chat and embedding client
- heartbeat daemon
- task queue
- event log and decision ledger
- layered JSON/JSONL memory files
- context packet builder
- permissioned tool executor
- verifier before success is committed

## WSL Setup

```bash
cd /mnt/d/codex/local-mind
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python daemon.py --once
```

## Model Setup

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
python model_client.py --warm
```

The daemon uses `config/local_mind.yaml`. By default it does not allow network,
delete operations, package installs, or git push actions from model proposals.
For Ollama 0.20.x, the configured negative `keep_alive` value includes a unit
(`-1m`) so the duration parser accepts it and keeps the model loaded.

## Run

```bash
./scripts/run_wsl.sh --once
./scripts/run_wsl.sh
```

## Memory Store

Initialize or refresh the SQLite memory layer from JSON/JSONL state:

```bash
./scripts/init_memory_wsl.sh
./scripts/maintain_memory_wsl.sh
./scripts/consolidate_memory_wsl.sh
```

This creates and refreshes:

- `data/memory.sqlite` for canonical memory records
- `vector_index/memory_index.sqlite` for Ollama embedding records

Search supports deterministic lexical scoring and optional vector scoring:

```bash
python memory_store.py --search status
python memory_store.py --search status --vector
./scripts/search_memory_wsl.sh status
```

The daemon also performs this sync on startup, so `init_memory_wsl.sh` is mainly
for inspection and manual refreshes.
When Ollama is online, daemon context retrieval uses vector search with lexical
fallback; when Ollama is offline, it falls back to lexical SQLite search.
The daemon also runs low-frequency embedding maintenance using the interval and
limit under `memory.embedding_maintenance_*` in `config/local_mind.yaml`.
Consolidation writes high-importance events to `data/episodic_memory.jsonl`,
updates `reports/daily_summary.md`, and archives low-value old events to
`data/event_archive.jsonl` once retention thresholds are exceeded.

Artifacts and evidence are written under `data/`, `reports/`, and
`vector_index/`.
