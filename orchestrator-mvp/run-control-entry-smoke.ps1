$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$embedded = Join-Path $root "..\tools\python311-embed\python.exe"
$script = Join-Path $root "tools\control_entry_smoke.py"

& $embedded $script

