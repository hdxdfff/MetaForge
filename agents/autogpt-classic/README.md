# AutoGPT Setup

This folder now supports two paths:

- `start-platform.ps1`: starts the official AutoGPT Platform with Docker Compose
- `run.ps1`: fallback script for AutoGPT Classic via Poetry

Recommended path:

1. Fill in `vendor\AutoGPT\autogpt_platform\.env`
2. Start Docker Desktop and wait until it shows Engine running
3. Run `.start-platform.ps1`
4. Open `http://localhost:3000`

Notes:

- `classic` is unsupported upstream and should be treated as legacy.
- Docker commands in this setup use `D:\codex\oi-state\dockerconfig` to avoid user-profile permission issues.
