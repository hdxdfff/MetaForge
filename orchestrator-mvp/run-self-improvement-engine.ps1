$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$embedded = Join-Path (Join-Path $root '..\tools\python311-embed') 'python.exe'
$script = Join-Path $root 'tools\self_improvement_engine.py'
& $embedded $script @args
