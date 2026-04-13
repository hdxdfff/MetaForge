from __future__ import annotations

import os
from urllib.parse import quote


DEFAULT_GITHUB_API_URL = "https://api.github.com"


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def resolve_github_api_url() -> str:
    return _first_env("ORCH_GITHUB_API_URL", "GITHUB_API_URL", default=DEFAULT_GITHUB_API_URL).rstrip("/")


def resolve_github_auth_mode() -> str:
    return _first_env("ORCH_GITHUB_AUTH_MODE", "GITHUB_AUTH_MODE", default="auto").lower()


def resolve_github_token() -> str:
    return _first_env(
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ORCH_GITHUB_APP_INSTALLATION_TOKEN",
        "GITHUB_APP_INSTALLATION_TOKEN",
        default="",
    )


def github_api_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    auth_token = (token or resolve_github_token()).strip()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def github_repo_api_url(repo: str, base_url: str | None = None) -> str:
    normalized = (repo or "").strip().removeprefix("https://github.com/").removeprefix("http://github.com/")
    normalized = normalized.removeprefix("github.com/")
    normalized = normalized.strip("/")
    if not normalized:
        raise ValueError("repo must be in owner/name form")
    if "/" not in normalized:
        raise ValueError("repo must be in owner/name form")
    owner, name = normalized.split("/", 1)
    root = (base_url or resolve_github_api_url()).rstrip("/")
    return f"{root}/repos/{quote(owner)}/{quote(name)}"

