param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ToolName,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'

. 'D:\codex\codex-toolchain.ps1' -Activate

if (-not (Get-Command $ToolName -ErrorAction SilentlyContinue)) {
    throw "tool not available: $ToolName"
}

& $ToolName @Args
exit $LASTEXITCODE
