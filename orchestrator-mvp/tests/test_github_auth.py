from __future__ import annotations

from app.config import read_external_integration_config
from tools.github_auth import github_api_headers, github_repo_api_url, resolve_github_token


def test_resolve_github_token_prefers_github_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GH_TOKEN", "gh-fallback")
    monkeypatch.setenv("ORCH_GITHUB_APP_INSTALLATION_TOKEN", "app-token")
    assert resolve_github_token() == "gh-token"


def test_resolve_github_token_accepts_installation_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("ORCH_GITHUB_APP_INSTALLATION_TOKEN", "app-token")
    assert resolve_github_token() == "app-token"


def test_github_repo_api_url_normalizes_owner_repo():
    assert github_repo_api_url("owner/name") == "https://api.github.com/repos/owner/name"
    assert github_repo_api_url("https://github.com/owner/name") == "https://api.github.com/repos/owner/name"


def test_github_api_headers_include_bearer_token():
    headers = github_api_headers("secret-token")
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Accept"] == "application/vnd.github+json"


def test_external_integration_config_includes_github_binding(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("ORCH_GITHUB_AUTH_MODE", "github_token")
    monkeypatch.setenv("ORCH_GITHUB_APP_ID", "123")
    monkeypatch.setenv("ORCH_GITHUB_APP_INSTALLATION_ID", "456")
    config = read_external_integration_config()
    github_binding = next(item for item in config["bindings"] if item["name"] == "GitHub")
    assert github_binding["api_key_configured"] is True
    assert github_binding["auth_mode"] == "github_token"
    assert github_binding["app_id_configured"] is True
    assert github_binding["installation_id_configured"] is True
