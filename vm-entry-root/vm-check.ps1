Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig
$vmx = $config.VmPath
$vmrunUsable = Test-CodexVmrunUsable -Config $config
$probeMode = Get-CodexVmProbeMode -Config $config

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

Write-Output "VM: $vmx"
Write-Output "IP: $($config.VmIp)"
Write-Output "User: $($config.GuestUser)"
Write-Output "Vmrun: $($config.VmrunExe)"
Write-Output "VmrunUsable: $vmrunUsable"
Write-Output "ExecutionRoot: ssh"
Write-Output "ProbeLayer: $probeMode"
if (-not $vmrunUsable) {
    Write-Output "ProbeStatus: degraded_optional_vmrun_probe"
    Write-Output "Mode: SSH primary path healthy; optional vmrun probe unavailable"
}
Write-Output ""

$sshArgs = @(
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
    "uname -a"
)

Write-Output "[1/3] SSH"
& $config.SshExe @sshArgs
$sshExit = $LASTEXITCODE
Write-Output "ssh_exit=$sshExit"
Write-Output ""

Write-Output "[2/3] VMware Tools"
if ($vmrunUsable) {
    $toolsExit = Invoke-CodexVmrun -Arguments @("-T", "ws", "checkToolsState", $vmx)
    Write-Output "tools_exit=$toolsExit"
}
else {
    Write-Output "tools_exit=skipped_vmrun_unavailable"
    Write-Output "tools_mode=optional_probe_skipped"
}
Write-Output ""

Write-Output "[3/3] Guest Ops"
if ($vmrunUsable -and $config.Password) {
    $guestOpsExit = Invoke-CodexVmrun -Arguments @("-T", "ws", "-gu", $config.GuestUser, "-gp", $config.Password, "fileExistsInGuest", $vmx, "/etc/hostname")
    Write-Output "guest_ops_exit=$guestOpsExit"
    Write-Output "guest_ops_mode=vmrun_guest_ops"
}
elseif (-not $vmrunUsable) {
    & "$PSScriptRoot\vm-ssh.ps1" -CommandString "hostname"
    $guestOpsExit = $LASTEXITCODE
    Write-Output "guest_ops_exit=$guestOpsExit"
    Write-Output "guest_ops_mode=ssh_primary"
}
else {
    Write-Output "guest_ops_skipped=no_password"
}
