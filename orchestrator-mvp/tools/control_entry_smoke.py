from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def _get_json(url: str, timeout: float = 5.0) -> tuple[int, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "metaforge-control-entry-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def _get_text(url: str, timeout: float = 5.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "metaforge-control-entry-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.status, body


def main() -> int:
    errors: list[str] = []

    try:
        status, payload = _get_json("http://127.0.0.1:8710/topology")
        if status != 200:
            errors.append(f"controller topology status={status}")
        elif payload.get("role_map", {}).get("Open WebUI", {}).get("role") != "human_entry":
            errors.append("controller topology does not mark Open WebUI as the human entry surface")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        errors.append(f"controller topology probe failed: {exc}")

    try:
        status, body = _get_text("http://127.0.0.1:3001/")
        if status != 200:
            errors.append(f"openwebui status={status}")
        elif not body.strip():
            errors.append("openwebui root response was empty")
    except (urllib.error.URLError, TimeoutError) as exc:
        errors.append(f"openwebui probe failed: {exc}")

    if errors:
        for error in errors:
            print(error)
        return 1

    print("control_entry_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
