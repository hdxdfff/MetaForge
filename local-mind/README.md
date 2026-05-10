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

Artifacts and evidence are written under `data/`, `reports/`, and
`vector_index/`.
