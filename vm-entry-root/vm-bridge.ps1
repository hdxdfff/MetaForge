[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig
$probeMode = Get-CodexVmProbeMode -Config $config
$vmrunUsable = Test-CodexVmrunUsable -Config $config

function Invoke-CodexScp {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $config.ScpExe @Arguments
    return $LASTEXITCODE
}

function Invoke-CodexVmrun {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $quotedArgs = $Arguments | ForEach-Object {
        if ($_ -match '\s') {
            '"' + ($_ -replace '"', '\"') + '"'
        }
        else {
            $_
        }
    }

    $commandLine = '"' + $config.VmrunExe + '" ' + ($quotedArgs -join ' ')
    & "$env:WINDIR\System32\cmd.exe" /c $commandLine
    return $LASTEXITCODE
}

function Get-BridgeStatus {
    param(
        [int]$SshExit,
        [int]$ScpPutExit,
        [int]$ScpGetExit
    )

    if ($SshExit -eq 0 -and $ScpPutExit -eq 0 -and $ScpGetExit -eq 0) {
        return "healthy"
    }

    if ($SshExit -eq 0) {
        return "degraded"
    }

    return "unavailable"
}

Assert-CodexVmFile -Path $config.SshExe -Label "ssh.exe"
Assert-CodexVmFile -Path $config.ScpExe -Label "scp.exe"
Assert-CodexVmFile -Path $config.SshKeyPath -Label "SSH private key"

$keyAcl = & "C:\Windows\System32\icacls.exe" $config.SshKeyPath 2>$null
$keyAclExit = $LASTEXITCODE
$workspaceTempDir = Join-Path $config.Workspace ".tmp\vm-bridge"
if (-not (Test-Path -LiteralPath $workspaceTempDir)) {
    New-Item -ItemType Directory -Path $workspaceTempDir -Force | Out-Null
}

$sessionId = [guid]::NewGuid().ToString("N")
$hostUploadPath = Join-Path $workspaceTempDir ("bridge-upload-" + $sessionId + ".txt")
$hostDownloadPath = Join-Path $workspaceTempDir ("bridge-download-" + $sessionId + ".txt")
$guestBridgePath = "/tmp/codex-bridge-$sessionId.txt"
$bridgePayload = "codex-bridge-$sessionId"
[System.IO.File]::WriteAllText($hostUploadPath, $bridgePayload, [System.Text.UTF8Encoding]::new($false))

$sshArgs = @(
    "-F", "NUL",
    "-i", $config.SshKeyPath,
    "-o", "IdentitiesOnly=yes",
    "-o", "PreferredAuthentications=publickey",
    "-o", "PubkeyAuthentication=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "ConnectTimeout=5",
    "-o", "ConnectionAttempts=1",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=1",
    "-o", "LogLevel=ERROR",
    (Get-CodexVmGuestTarget -Config $config),
    "printf bridge-ok"
)

$scpPutArgs = @(
    "-F", "NUL",
    "-i", $config.SshKeyPath,
    "-o", "IdentitiesOnly=yes",
    "-o", "PreferredAuthentications=publickey",
    "-o", "PubkeyAuthentication=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "ConnectTimeout=5",
    "-o", "ConnectionAttempts=1",
    "-o", "LogLevel=ERROR",
    $hostUploadPath,
    ("{0}:{1}" -f (Get-CodexVmGuestTarget -Config $config), $guestBridgePath)
)

$scpGetArgs = @(
    "-F", "NUL",
    "-i", $config.SshKeyPath,
    "-o", "IdentitiesOnly=yes",
    "-o", "PreferredAuthentications=publickey",
    "-o", "PubkeyAuthentication=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "ConnectTimeout=5",
    "-o", "ConnectionAttempts=1",
    "-o", "LogLevel=ERROR",
    ("{0}:{1}" -f (Get-CodexVmGuestTarget -Config $config), $guestBridgePath),
    $hostDownloadPath
)

Write-Output "ExecutionRoot: ssh"
Write-Output "TransportPrimary: ssh_scp"
Write-Output "TransportProbe: $probeMode"
Write-Output "SshKeyPath: $($config.SshKeyPath)"
Write-Output "VmrunUsable: $vmrunUsable"
Write-Output ""

Write-Output "[1/5] Key ACL"
if ($keyAclExit -eq 0) {
    Write-Output "key_acl_exit=0"
    $keyAcl | Write-Output
}
else {
    Write-Output "key_acl_exit=$keyAclExit"
}
Write-Output ""

Write-Output "[2/5] SSH command"
& $config.SshExe @sshArgs
$sshExit = $LASTEXITCODE
Write-Output ""
Write-Output "ssh_exit=$sshExit"
Write-Output ""

Write-Output "[3/5] SCP upload"
$scpPutExit = Invoke-CodexScp -Arguments $scpPutArgs
Write-Output "scp_put_exit=$scpPutExit"
Write-Output ""

Write-Output "[4/5] SCP download"
$scpGetExit = Invoke-CodexScp -Arguments $scpGetArgs
Write-Output "scp_get_exit=$scpGetExit"
if ($scpGetExit -eq 0 -and (Test-Path -LiteralPath $hostDownloadPath)) {
    $downloaded = (Get-Content -LiteralPath $hostDownloadPath -Raw -ErrorAction SilentlyContinue)
    Write-Output ("scp_roundtrip_match=" + $(if ($downloaded -eq $bridgePayload) { "yes" } else { "no" }))
}
Write-Output ""

Write-Output "[5/5] Guest Ops probe"
if ((Get-CodexVmVmrunProbeEnabled) -and $vmrunUsable -and $config.Password) {
    $guestOpsExit = Invoke-CodexVmrun -Arguments @("-T", "ws", "-gu", $config.GuestUser, "-gp", $config.Password, "fileExistsInGuest", $config.VmPath, $guestBridgePath)
    Write-Output "guest_ops_exit=$guestOpsExit"
    Write-Output "guest_ops_mode=vmrun_optional"
}
elseif (-not $vmrunUsable) {
    Write-Output "guest_ops_exit=skipped_vmrun_unavailable"
    Write-Output "guest_ops_mode=optional_probe_skipped"
}
else {
    Write-Output "guest_ops_exit=skipped_no_password"
    Write-Output "guest_ops_mode=optional_probe_skipped"
}
Write-Output ""

$bridgeStatus = Get-BridgeStatus -SshExit $sshExit -ScpPutExit $scpPutExit -ScpGetExit $scpGetExit
Write-Output "bridge_status=$bridgeStatus"
Write-Output ("bridge_result_code=" + $(if ($bridgeStatus -eq "healthy") { 0 } elseif ($bridgeStatus -eq "degraded") { 10 } else { 20 }))

$cleanupArgs = @(
    "-F", "NUL",
    "-i", $config.SshKeyPath,
    "-o", "IdentitiesOnly=yes",
    "-o", "PreferredAuthentications=publickey",
    "-o", "PubkeyAuthentication=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "LogLevel=ERROR",
    (Get-CodexVmGuestTarget -Config $config),
    ("rm -f " + $guestBridgePath)
)
& $config.SshExe @cleanupArgs *> $null

Remove-Item -LiteralPath $hostUploadPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $hostDownloadPath -Force -ErrorAction SilentlyContinue

if ($bridgeStatus -eq "healthy") {
    exit 0
}
elseif ($bridgeStatus -eq "degraded") {
    exit 10
}
else {
    exit 20
}
