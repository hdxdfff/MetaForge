$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

docker compose -f .\docker-compose.control-entry.yml up -d

