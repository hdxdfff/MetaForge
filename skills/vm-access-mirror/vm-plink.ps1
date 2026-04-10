[CmdletBinding(DefaultParameterSetName = "CommandArgs")]
param(
    [Parameter(ParameterSetName = "CommandArgs")]
    [Parameter(ParameterSetName = "CommandString")]
    [switch]$PrintConfig,
    [Parameter(ParameterSetName = "CommandString")]
    [string]$CommandString,
    [Parameter(ParameterSetName = "CommandArgs", ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig

if ($PrintConfig) {
    $config | Select-Object VmIp, GuestUser, VmPath, PlinkExe, PlinkKeyPath, SshHostKey
    return
}

Assert-CodexVmFile -Path $config.PlinkExe -Label "plink.exe"
Assert-CodexVmFile -Path $config.PlinkKeyPath -Label "PuTTY private key"

$hasCommandString = $PSCmdlet.ParameterSetName -eq "CommandString"
$hasCommandArgs = $PSCmdlet.ParameterSetName -eq "CommandArgs" -and $null -ne $Command -and $Command.Count -gt 0

$args = @(
    "-batch",
    "-i", $config.PlinkKeyPath,
    "-hostkey", $config.SshHostKey,
    "-noagent",
    "-ssh",
    ("{0}@{1}" -f $config.GuestUser, $config.VmIp)
)

if ($hasCommandString) {
    $args += $CommandString
}
elseif ($hasCommandArgs) {
    $args += [string]::Join(" ", $Command)
}

& $config.PlinkExe @args
exit $LASTEXITCODE
