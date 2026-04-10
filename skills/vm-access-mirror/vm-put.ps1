param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$HostPath,
    [Parameter(Mandatory = $true, Position = 1)]
    [string]$GuestPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig
Assert-CodexVmFile -Path $config.ScpExe -Label "scp.exe"
Assert-CodexVmFile -Path $config.SshKeyPath -Label "SSH private key"

$resolvedHostPath = (Resolve-Path -LiteralPath $HostPath).ProviderPath
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
    $resolvedHostPath,
    ("{0}:{1}" -f (Get-CodexVmGuestTarget -Config $config), $GuestPath)
)

& $config.ScpExe @args
exit $LASTEXITCODE
