$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$embedded = Join-Path $root "..\tools\python311-embed\python.exe"
$bootstrap = Join-Path $root "bootstrap_runner.py"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

if (-not (Test-Path $embedded)) {
    throw "Missing embedded Python runtime: $embedded"
}

& $embedded $bootstrap ".\desktop_app.py"
