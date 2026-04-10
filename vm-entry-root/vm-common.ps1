Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-CodexDefaultVmrunExe {
    $candidates = @(
        "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
        "C:\Program Files\VMware\VMware Workstation\vmrun.exe",
        "D:\vmrun.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    if ($env:CODEX_VM_ALLOW_VMRUN_RECURSIVE_SCAN) {
        $allowScan = $env:CODEX_VM_ALLOW_VMRUN_RECURSIVE_SCAN.Trim().ToLowerInvariant()
        if ($allowScan -in @("1", "true", "yes", "on")) {
            $dRoot = "D:\"
            if (Test-Path -LiteralPath $dRoot) {
                $nestedMatch = Get-ChildItem -LiteralPath $dRoot -Recurse -Filter vmrun.exe -ErrorAction SilentlyContinue |
                    Select-Object -First 1 -ExpandProperty FullName
                if ($nestedMatch) {
                    return $nestedMatch
                }
            }
        }
    }

    "vmrun.exe"
}

function Get-CodexDefaultScpExe {
    $candidates = @(
        "C:\Windows\System32\OpenSSH\scp.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    "scp.exe"
}

function Get-CodexDefaultPlinkExe {
    $workspaceCandidate = "D:\codex\tools\putty\plink.exe"
    $candidates = @(
        $workspaceCandidate,
        "C:\Program Files\PuTTY\plink.exe",
        "C:\Program Files (x86)\PuTTY\plink.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    "plink.exe"
}

function Get-CodexDefaultPlinkKeyPath {
    $workspaceCandidate = "D:\codex\.vm-keys\id_ed25519_host.ppk"
    if (Test-Path -LiteralPath $workspaceCandidate) {
        return $workspaceCandidate
    }

    $legacyCandidate = "D:\codex\.vm-keys\id_ed25519.ppk"
    if (Test-Path -LiteralPath $legacyCandidate) {
        return $legacyCandidate
    }

    $workspaceCandidate
}

function Get-CodexVmConfig {
    $workspace = "D:\codex"
    $workspacePasswordFile = Join-Path $workspace ".vm-keys\guest-password.txt"
    $passwordFileDefault = $workspacePasswordFile
    $preferredSshKey = Join-Path $workspace ".vm-keys\id_ed25519_host"
    $secondarySshKey = Join-Path $workspace ".vm-keys\id_ed25519_strict"
    $legacySshKey = Join-Path $workspace ".vm-keys\id_ed25519"
    $sshKeyDefault = if (Test-Path -LiteralPath $preferredSshKey) {
        $preferredSshKey
    }
    elseif (Test-Path -LiteralPath $secondarySshKey) {
        $secondarySshKey
    }
    elseif (Test-Path -LiteralPath $legacySshKey) {
        $legacySshKey
    }
    else {
        $legacySshKey
    }

    $config = [ordered]@{
        Workspace = $workspace
        VmrunExe = if ($env:CODEX_VM_VMRUN) { $env:CODEX_VM_VMRUN } else { Get-CodexDefaultVmrunExe }
        SshExe = if ($env:CODEX_VM_SSH) { $env:CODEX_VM_SSH } else { "C:\Windows\System32\OpenSSH\ssh.exe" }
        ScpExe = if ($env:CODEX_VM_SCP) { $env:CODEX_VM_SCP } else { Get-CodexDefaultScpExe }
        PlinkExe = if ($env:CODEX_VM_PLINK) { $env:CODEX_VM_PLINK } else { Get-CodexDefaultPlinkExe }
        VmPath = if ($env:CODEX_VM_VMX) { $env:CODEX_VM_VMX } else { "D:\VMs\orchestrator-mvp-ubuntu-cloud\orchestrator-mvp-ubuntu-cloud.vmx" }
        VmIp = if ($env:CODEX_VM_IP) { $env:CODEX_VM_IP } else { "192.168.202.130" }
        GuestUser = if ($env:CODEX_VM_USER) { $env:CODEX_VM_USER } else { "codex" }
        SshHostKey = if ($env:CODEX_VM_SSH_HOSTKEY) { $env:CODEX_VM_SSH_HOSTKEY } else { "ssh-ed25519 255 SHA256:cBLPDjcTtWkdmXxThl3Uiv28LAD3WaihqPUL9q8j2l8" }
        SshKeyPath = if ($env:CODEX_VM_SSH_KEY) { $env:CODEX_VM_SSH_KEY } else { $sshKeyDefault }
        PlinkKeyPath = if ($env:CODEX_VM_PLINK_KEY) { $env:CODEX_VM_PLINK_KEY } else { Get-CodexDefaultPlinkKeyPath }
        PasswordFile = if ($env:CODEX_VM_PASSWORD_FILE) { $env:CODEX_VM_PASSWORD_FILE } else { $passwordFileDefault }
        Password = if ($env:CODEX_VM_PASSWORD) { $env:CODEX_VM_PASSWORD } else { $null }
    }

    if (-not $config.Password -and (Test-Path -LiteralPath $config.PasswordFile)) {
        $config.Password = (Get-Content -LiteralPath $config.PasswordFile -Raw).Trim()
    }

    [pscustomobject]$config
}

function Get-CodexVmGuestTarget {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config
    )

    "$($Config.GuestUser)@$($Config.VmIp)"
}

function Assert-CodexVmPassword {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config
    )

    if (-not $Config.Password) {
        throw "Guest password is not configured. Set CODEX_VM_PASSWORD or create $($Config.PasswordFile)."
    }
}

function Assert-CodexVmFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label not found: $Path"
    }
}

function Test-CodexVmrunUsable {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config
    )

    if (-not (Test-Path -LiteralPath $Config.VmrunExe)) {
        return $false
    }

    try {
        & $Config.VmrunExe -T ws checkToolsState $Config.VmPath *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-CodexVmVmrunProbeEnabled {
    if ($env:CODEX_VM_ENABLE_VMRUN_PROBE) {
        $value = $env:CODEX_VM_ENABLE_VMRUN_PROBE.Trim().ToLowerInvariant()
        return $value -in @("1", "true", "yes", "on")
    }
    return $false
}

function Get-CodexVmProbeMode {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config
    )

    if ((Get-CodexVmVmrunProbeEnabled) -and (Test-CodexVmrunUsable -Config $Config)) {
        return "vmrun_probe_available"
    }

    return "ssh_primary_only"
}

