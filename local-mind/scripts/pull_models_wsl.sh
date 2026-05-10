#!/usr/bin/env bash
set -euo pipefail

ollama pull qwen3:8b
ollama pull nomic-embed-text
cd /mnt/d/codex/local-mind
. .venv/bin/activate
python model_client.py --warm
