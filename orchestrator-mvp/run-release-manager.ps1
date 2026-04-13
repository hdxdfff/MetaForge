param(
    [switch]$Advance
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$embedded = Join-Path (Join-Path $root '..\tools\python311-embed') 'python.exe'
$script = Join-Path (Join-Path $root 'tools') 'release_manager.py'
$argsList = @($script)
if ($Advance) {
    $argsList += '--advance'
}
& $embedded @argsList
exit $LASTEXITCODE
