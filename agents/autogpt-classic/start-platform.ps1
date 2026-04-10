$ErrorActionPreference = "Stop"
$env:DOCKER_CONFIG = "D:\codex\oi-state\dockerconfig"
$PlatformDir = "D:\codex\agents\autogpt-classic\vendor\AutoGPT\autogpt_platform"

if (-not (Test-Path (Join-Path $PlatformDir ".env"))) {
    Copy-Item (Join-Path $PlatformDir ".env.default") (Join-Path $PlatformDir ".env")
}

Push-Location $PlatformDir
try {
    docker compose up -d
}
finally {
    Pop-Location
}
