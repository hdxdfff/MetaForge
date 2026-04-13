param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$GuestPath,
    [Parameter(Mandatory = $true, Position = 1)]
    [string]$HostPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig
$probeMode = Get-CodexVmProbeMode -Config $config
Assert-CodexVmFile -Path $config.ScpExe -Label "scp.exe"
Assert-CodexVmFile -Path $config.SshKeyPath -Label "SSH private key"
Write-Output "vm-get mode: scp_primary"
Write-Output ("vm-get probe: " + $probeMode)

$resolvedHostPath = [System.IO.Path]::GetFullPath($HostPath)
$hostDir = Split-Path -Parent $resolvedHostPath
if ($hostDir -and -not (Test-Path -LiteralPath $hostDir)) {
    New-Item -ItemType Directory -Path $hostDir | Out-Null
}

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
    ("{0}:{1}" -f (Get-CodexVmGuestTarget -Config $config), $GuestPath),
    $resolvedHostPath
)

& $config.ScpExe @args
exit $LASTEXITCODE
