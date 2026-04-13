#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || printf '%s' ../../tools/python311-embed/python.exe)}"
"$PYTHON_BIN" tools/system_toolchain.py build
