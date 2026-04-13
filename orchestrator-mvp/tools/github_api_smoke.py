from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.github_auth import (
    github_api_headers,
    github_repo_api_url,
    resolve_github_api_url,
    resolve_github_auth_mode,
    resolve_github_token,
)
from tools.io_utils import atomic_write_json


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "reports" / "github-auth-smoke.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def build_report(repo: str, output: Path | None = None) -> dict[str, Any]:
    token = resolve_github_token()
    if not token:
        raise SystemExit(
            "No GitHub token found. Set GITHUB_TOKEN, GH_TOKEN, or ORCH_GITHUB_APP_INSTALLATION_TOKEN."
        )
    api_url = github_repo_api_url(repo, resolve_github_api_url())
    headers = github_api_headers(token)
    try:
        repo_payload = _read_json(api_url, headers)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SystemExit(f"GitHub API request failed: HTTP {exc.code} {body}".strip()) from exc

    report: dict[str, Any] = {
        "updated_at": _utc(),
        "status": "pass",
        "auth_mode": resolve_github_auth_mode(),
        "api_url": api_url,
        "repository": {
            "full_name": repo_payload.get("full_name"),
            "private": repo_payload.get("private"),
            "default_branch": repo_payload.get("default_branch"),
            "permissions": repo_payload.get("permissions") or {},
            "visibility": repo_payload.get("visibility"),
        },
        "token_source": "installation"
        if resolve_github_auth_mode() == "github_app"
        else "github-token",
    }
    if output is not None:
        _write_report(output, report)
        report["report_path"] = str(output)
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test GitHub API authentication.")
    parser.add_argument("--repo", default="", help="Repository in owner/name form. Defaults to GITHUB_REPOSITORY.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Where to write the JSON report.")
    args = parser.parse_args(argv[1:])
    repo = args.repo or __import__("os").environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise SystemExit("Repository not provided. Pass --repo or set GITHUB_REPOSITORY.")
    report = build_report(repo, Path(args.output) if args.output else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
