Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig
$vmx = $config.VmPath

Write-Output "VM: $vmx"
Write-Output "IP: $($config.VmIp)"
Write-Output "User: $($config.GuestUser)"
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
& $config.VmrunExe -T ws checkToolsState $vmx
$toolsExit = $LASTEXITCODE
Write-Output "tools_exit=$toolsExit"
Write-Output ""

Write-Output "[3/3] Guest Ops"
if ($config.Password) {
    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password fileExistsInGuest $vmx "/etc/hostname"
    $guestOpsExit = $LASTEXITCODE
    Write-Output "guest_ops_exit=$guestOpsExit"
}
else {
    Write-Output "guest_ops_skipped=no_password"
}
