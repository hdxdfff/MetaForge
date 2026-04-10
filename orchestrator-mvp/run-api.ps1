$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$embedded = Join-Path $root "..\tools\python311-embed\python.exe"
$bootstrap = Join-Path $root "bootstrap_runner.py"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

& $embedded $bootstrap -m uvicorn app.main:app --host 127.0.0.1 --port 8787
