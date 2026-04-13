param(
    [string]$StateRoot = $env:OPENCODE_STATE_ROOT,
    [int]$SnapshotSizeLimitGiB = 2
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($StateRoot)) {
    $StateRoot = 'D:\codex\oi-state-opencode'
}

$snapshotGlobal = Join-Path $StateRoot 'xdg\opencode\snapshot\global'
if (-not (Test-Path $snapshotGlobal)) {
    exit 0
}

$sizeBytes = 0
try {
    $sizeBytes = (Get-ChildItem -LiteralPath $snapshotGlobal -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sizeBytes) { $sizeBytes = 0 }
} catch {
    $sizeBytes = 0
}

$limitBytes = $SnapshotSizeLimitGiB * 1GB
if ($sizeBytes -lt $limitBytes) {
    exit 0
}

Remove-Item -LiteralPath $snapshotGlobal -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Split-Path -Parent $snapshotGlobal) -Force | Out-Null

$logDir = Join-Path $StateRoot 'xdg\opencode\log'
if (Test-Path $logDir) {
    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
    Set-Content -Path (Join-Path $logDir "snapshot-rotated-$stamp.txt") -Value "Rotated OpenCode snapshot/global because it exceeded $SnapshotSizeLimitGiB GiB." -Encoding UTF8
}
