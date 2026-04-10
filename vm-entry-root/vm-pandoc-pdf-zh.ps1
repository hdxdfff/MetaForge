param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputPath,
    [Parameter(Position = 1)]
    [string]$OutputPath,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PandocArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\vm-common.ps1"

function ConvertTo-CodexBashLiteral {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    "'" + ($Value -replace "'", "'""'""'") + "'"
}

function Invoke-CodexVmSsh {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config,
        [Parameter(Mandatory = $true)]
        [string]$RemoteCommand
    )

    $args = @(
        "-F", "NUL",
        "-i", $Config.SshKeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PubkeyAuthentication=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "LogLevel=ERROR",
        (Get-CodexVmGuestTarget -Config $Config),
        ("bash -lc " + (ConvertTo-CodexBashLiteral -Value $RemoteCommand))
    )

    & $Config.SshExe @args
    if ($LASTEXITCODE -ne 0) {
        throw "VM SSH command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-CodexVmScp {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config,
        [Parameter(Mandatory = $true)]
        [string[]]$CopyArgs
    )

    $args = @(
        "-F", "NUL",
        "-i", $Config.SshKeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PubkeyAuthentication=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "LogLevel=ERROR"
    ) + $CopyArgs

    & $Config.ScpExe @args
    if ($LASTEXITCODE -ne 0) {
        throw "VM SCP command failed with exit code $LASTEXITCODE."
    }
}

$config = Get-CodexVmConfig
Assert-CodexVmFile -Path $config.SshExe -Label "ssh.exe"
Assert-CodexVmFile -Path $config.ScpExe -Label "scp.exe"
Assert-CodexVmFile -Path $config.SshKeyPath -Label "SSH private key"

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).ProviderPath
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = [System.IO.Path]::ChangeExtension($resolvedInput, ".pdf")
}
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$outputDir = Split-Path -Parent $resolvedOutput
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$sessionId = [guid]::NewGuid().ToString("N")
$guestDir = "/tmp/codex-pandoc-$sessionId"
$guestInput = "$guestDir/" + [System.IO.Path]::GetFileName($resolvedInput)
$guestOutput = "$guestDir/output.pdf"
$guestTarget = Get-CodexVmGuestTarget -Config $config
$extraArgText = ""
if ($null -ne $PandocArgs -and $PandocArgs.Count -gt 0) {
    $extraArgText = " " + (($PandocArgs | ForEach-Object { ConvertTo-CodexBashLiteral -Value $_ }) -join " ")
}

try {
    Invoke-CodexVmSsh -Config $config -RemoteCommand ("mkdir -p " + (ConvertTo-CodexBashLiteral -Value $guestDir))
    Invoke-CodexVmScp -Config $config -CopyArgs @($resolvedInput, "${guestTarget}:$guestInput")

    $remoteBuild = @(
        "set -euo pipefail"
        "pandoc-pdf-zh " +
            (ConvertTo-CodexBashLiteral -Value $guestInput) + " " +
            (ConvertTo-CodexBashLiteral -Value $guestOutput) +
            $extraArgText
    ) -join "; "
    Invoke-CodexVmSsh -Config $config -RemoteCommand $remoteBuild

    Invoke-CodexVmScp -Config $config -CopyArgs @("${guestTarget}:$guestOutput", $resolvedOutput)
}
finally {
    try {
        Invoke-CodexVmSsh -Config $config -RemoteCommand ("rm -rf " + (ConvertTo-CodexBashLiteral -Value $guestDir))
    }
    catch {
    }
}

Write-Output $resolvedOutput
