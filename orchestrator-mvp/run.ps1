$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from template. Fill in OPENAI_API_KEY before real runs."
}

python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8787
