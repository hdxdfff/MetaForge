# GitHub Automation Setup

This repository now supports two GitHub API authentication paths:

- `GITHUB_TOKEN` in GitHub Actions for the default repo-local workflow path
- GitHub App installation tokens for the higher-trust automation path

## Workflow paths

- `.github/workflows/ci.yml` runs with minimal `contents: read` permissions.
- `.github/workflows/github-auth-smoke.yml` can be triggered manually and will:
  - use `GITHUB_TOKEN` by default, or
  - mint a GitHub App installation token through `actions/create-github-app-token@v2`

## GitHub App configuration

To enable the GitHub App path in Actions, configure:

- repository variable `ORCH_GITHUB_APP_ID`
- repository secret `ORCH_GITHUB_APP_PRIVATE_KEY`

Optional environment variables for local or external runs:

- `ORCH_GITHUB_AUTH_MODE`
- `ORCH_GITHUB_APP_INSTALLATION_TOKEN`
- `ORCH_GITHUB_APP_OWNER`
- `ORCH_GITHUB_APP_INSTALLATION_ID`
- `ORCH_GITHUB_API_URL`

## Local smoke

Run the GitHub API smoke helper locally when you already have a token:

```powershell
python tools/python_tooling.py github-smoke --repo owner/name
```

The helper writes a JSON report to `reports/github-auth-smoke.json`.
