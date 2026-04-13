param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root 'tools\python311-embed\python.exe'
$script = Join-Path $root 'opencode-factory.py'

& $python $script @Args
exit $LASTEXITCODE
