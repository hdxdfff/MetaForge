$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$embedded = Join-Path (Join-Path $root '..\tools\python311-embed') 'python.exe'
$script = Join-Path $root 'tools\budget_suppression_report.py'
& $embedded $script @args
