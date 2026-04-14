Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$workspace = "D:\codex"
$python = Join-Path $workspace "tools\python311-embed\python.exe"
$script = Join-Path $workspace "tools\generated_sync.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Embedded Python not found: $python"
}

if (-not (Test-Path -LiteralPath $script)) {
    throw "Generated sync helper not found: $script"
}

& $python $script --quiet --cooldown-seconds 240 --reason scheduled
exit $LASTEXITCODE
