param(
    [switch]$NoWait,
    [switch]$NoCapture,
    [switch]$PrintConfig,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

$config = Get-CodexVmConfig

if ($PrintConfig) {
    $config | Select-Object VmIp, GuestUser, VmPath, VmrunExe, PasswordFile
    return
}

Assert-CodexVmFile -Path $config.VmrunExe -Label "vmrun.exe"
Assert-CodexVmPassword -Config $config

if ($Command.Count -eq 0) {
    throw "Provide a guest command. Example: .\vm-run.ps1 uname -a"
}

$commandText = [string]::Join(" ", $Command)
if ($NoWait -or $NoCapture) {
    $args = @(
        "-T", "ws",
        "-gu", $config.GuestUser,
        "-gp", $config.Password,
        "runProgramInGuest",
        $config.VmPath
    )

    if ($NoWait) {
        $args += "-noWait"
    }

    $args += @("/bin/bash", "-lc", $commandText)
    & $config.VmrunExe @args
    exit $LASTEXITCODE
}

$sessionId = [guid]::NewGuid().ToString("N")
$guestStdout = "/tmp/codex-vmrun-$sessionId.out"
$guestStatus = "/tmp/codex-vmrun-$sessionId.exit"
$guestScript = "/tmp/codex-vmrun-$sessionId.sh"
$localTempDir = if ($env:CODEX_VM_TMP_DIR) {
    $env:CODEX_VM_TMP_DIR
} else {
    Join-Path $env:TEMP "codex-vmrun"
}
$localStdout = Join-Path $localTempDir "codex-vmrun-$sessionId.out"
$localStatus = Join-Path $localTempDir "codex-vmrun-$sessionId.exit"
$localScript = Join-Path $localTempDir "codex-vmrun-$sessionId.sh"
$scriptExit = 0

if (-not (Test-Path -LiteralPath $localTempDir)) {
    New-Item -ItemType Directory -Path $localTempDir | Out-Null
}

$scriptBody = @"
#!/usr/bin/env bash
($commandText) >'$guestStdout' 2>&1
rc=`$?
printf '%s' "`$rc" >'$guestStatus'
exit "`$rc"
"@

$normalizedScriptBody = $scriptBody -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($localScript, $normalizedScriptBody, [System.Text.Encoding]::ASCII)

try {
    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password CopyFileFromHostToGuest $config.VmPath $localScript $guestScript
    $scriptExit = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
        return
    }

    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password runProgramInGuest $config.VmPath /bin/bash $guestScript
    $scriptExit = $LASTEXITCODE

    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password CopyFileFromGuestToHost $config.VmPath $guestStdout $localStdout
    $scriptExit = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
        return
    }

    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password CopyFileFromGuestToHost $config.VmPath $guestStatus $localStatus
    $scriptExit = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
        return
    }

    if (Test-Path -LiteralPath $localStdout) {
        $stdout = Get-Content -LiteralPath $localStdout -Raw
        if ($null -ne $stdout -and $stdout.Length -gt 0) {
            Write-Output $stdout.TrimEnd("`r", "`n")
        }
    }

    $guestExitCode = 0
    if (Test-Path -LiteralPath $localStatus) {
        $rawExitContent = Get-Content -LiteralPath $localStatus -Raw
        if ($null -ne $rawExitContent) {
            $rawExit = $rawExitContent.Trim()
            if ($rawExit) {
                $guestExitCode = [int]$rawExit
            }
        }
    }
    $scriptExit = $guestExitCode
}
finally {
    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password deleteFileInGuest $config.VmPath $guestScript *> $null
    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password deleteFileInGuest $config.VmPath $guestStdout *> $null
    & $config.VmrunExe -T ws -gu $config.GuestUser -gp $config.Password deleteFileInGuest $config.VmPath $guestStatus *> $null

    if (Test-Path -LiteralPath $localScript) {
        Remove-Item -LiteralPath $localScript -Force
    }
    if (Test-Path -LiteralPath $localStdout) {
        Remove-Item -LiteralPath $localStdout -Force
    }
    if (Test-Path -LiteralPath $localStatus) {
        Remove-Item -LiteralPath $localStatus -Force
    }
}

exit $scriptExit
