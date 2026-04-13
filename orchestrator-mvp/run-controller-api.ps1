$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$embedded = Join-Path $root "..\tools\python311-embed\python.exe"
$bootstrap = Join-Path $root "tools\serve_controller_api.py"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

& $embedded $bootstrap

