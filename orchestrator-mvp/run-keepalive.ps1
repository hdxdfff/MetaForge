$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$embedded = Join-Path (Join-Path $root '..\tools\python311-embed') 'python.exe'
$toolsDir = Join-Path $root 'tools'
$script = Join-Path $toolsDir 'network_keepalive.py'
& $embedded $script --loop --interval 60
