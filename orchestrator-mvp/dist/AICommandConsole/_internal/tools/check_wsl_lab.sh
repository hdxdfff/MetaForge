#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-/mnt/d/codex}"
TARGET_DIR="${2:-$ROOT_DIR/generated/toy-os-demo}"

check_cmd() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    printf '[ok] %s -> %s\n' "$name" "$(command -v "$name")"
  else
    printf '[missing] %s\n' "$name"
  fi
}

echo "[health] linux user: $(whoami)"
echo "[health] kernel: $(uname -a)"
echo "[health] root dir: $ROOT_DIR"
echo "[health] target dir: $TARGET_DIR"

echo "[health] toolchain"
check_cmd python3
check_cmd gcc
check_cmd g++
check_cmd make
check_cmd cmake
check_cmd nasm
check_cmd qemu-system-i386
check_cmd git

if [ -d "$TARGET_DIR" ]; then
  echo "[health] target contents"
  find "$TARGET_DIR" -maxdepth 2 -type f | sort
else
  echo "[health] target dir not found"
fi

if [ -f "$ROOT_DIR/orchestrator-mvp/tools/score_toy_os.py" ]; then
  echo "[health] scoring available"
else
  echo "[health] scoring script missing"
fi