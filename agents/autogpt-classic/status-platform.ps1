$ErrorActionPreference = "Stop"
$env:DOCKER_CONFIG = "D:\codex\oi-state\dockerconfig"
$PlatformDir = "D:\codex\agents\autogpt-classic\vendor\AutoGPT\autogpt_platform"
Push-Location $PlatformDir
try {
    docker compose ps
}
finally {
    Pop-Location
}
