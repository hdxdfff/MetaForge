$ErrorActionPreference = "Stop"
$env:DOCKER_CONFIG = "D:\codex\oi-state\dockerconfig"
$env:LOCALAPPDATA = "D:\codex\oi-state\localappdata"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClassicDir = Join-Path $Root "vendor\AutoGPT\classic\original_autogpt"
$Poetry = "D:\codex\tools\python311-embed\Scripts\poetry.exe"

if (-not (Test-Path $ClassicDir)) {
    throw "AutoGPT classic is not set up. Run .\\setup.ps1 first."
}

if (-not (Test-Path $Poetry)) {
    throw "Poetry is not installed. Run .\\setup.ps1 -InstallPoetry first."
}

Push-Location $ClassicDir
try {
    & $Poetry install
    & $Poetry run autogpt --help
}
finally {
    Pop-Location
}
