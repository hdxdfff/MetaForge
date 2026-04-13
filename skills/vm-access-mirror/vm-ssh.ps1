[CmdletBinding(DefaultParameterSetName = "CommandArgs")]
param(
    [Parameter(ParameterSetName = "CommandArgs")]
    [Parameter(ParameterSetName = "CommandString")]
    [Parameter(ParameterSetName = "ScriptPath")]
    [switch]$PrintConfig,
    [Parameter(ParameterSetName = "CommandString")]
    [string]$CommandString,
    [Parameter(ParameterSetName = "ScriptPath")]
    [string]$ScriptPath,
    [Parameter(ParameterSetName = "CommandArgs", ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig

if ($PrintConfig) {
    $config | Select-Object VmIp, GuestUser, VmPath, SshExe, SshKeyPath, PasswordFile
    return
}

Assert-CodexVmFile -Path $config.SshExe -Label "ssh.exe"
Assert-CodexVmFile -Path $config.SshKeyPath -Label "SSH private key"

$hasCommandString = $PSCmdlet.ParameterSetName -eq "CommandString"
$hasScriptPath = $PSCmdlet.ParameterSetName -eq "ScriptPath"
$hasCommandArgs = $PSCmdlet.ParameterSetName -eq "CommandArgs" -and $null -ne $Command -and $Command.Count -gt 0

$args = @(
    "-F", "NUL",
    "-i", $config.SshKeyPath,
    "-o", "IdentitiesOnly=yes",
    "-o", "PreferredAuthentications=publickey",
    "-o", "PubkeyAuthentication=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "LogLevel=ERROR",
    (Get-CodexVmGuestTarget -Config $config)
)

if ($hasScriptPath) {
    $resolvedScript = (Resolve-Path -LiteralPath $ScriptPath).ProviderPath
    Assert-CodexVmFile -Path $config.ScpExe -Label "scp.exe"

    $sessionId = [guid]::NewGuid().ToString("N")
    $guestScript = "/tmp/codex-ssh-script-$sessionId.sh"
    $scpArgs = @(
        "-F", "NUL",
        "-i", $config.SshKeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PubkeyAuthentication=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "LogLevel=ERROR",
        $resolvedScript,
        ("{0}:{1}" -f (Get-CodexVmGuestTarget -Config $config), $guestScript)
    )

    try {
        & $config.ScpExe @scpArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        $runArgs = $args + ("bash " + $guestScript)
        & $config.SshExe @runArgs
        $scriptExit = $LASTEXITCODE
    }
    finally {
        $cleanupArgs = $args + ("rm -f " + $guestScript)
        & $config.SshExe @cleanupArgs *> $null
    }

    exit $scriptExit
}

if ($hasCommandString) {
    $args += $CommandString
}
elseif ($hasCommandArgs) {
    $args += [string]::Join(" ", $Command)
}

& $config.SshExe @args
exit $LASTEXITCODE
