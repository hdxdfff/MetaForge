param(
    [switch]$InstallPoetry
)

$ErrorActionPreference = "Stop"
$env:LOCALAPPDATA = "D:\codex\oi-state\localappdata"
$Pip = "D:\codex\tools\python311-embed\Scripts\pip.exe"
$Git = "D:\codex\tools\mingit-2.53.0-64-bit\cmd\git.exe"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VendorDir = Join-Path $Root "vendor"
$RepoDir = Join-Path $VendorDir "AutoGPT"
$ClassicDir = Join-Path $RepoDir "classic\original_autogpt"

New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

if (-not (Test-Path $RepoDir)) {
    & $Git clone https://github.com/Significant-Gravitas/AutoGPT.git $RepoDir
}

if (-not (Test-Path $ClassicDir)) {
    throw "AutoGPT classic directory was not found at $ClassicDir"
}

if ($InstallPoetry) {
    & $Pip install poetry
}

if (-not (Test-Path (Join-Path $ClassicDir ".env"))) {
    if (Test-Path (Join-Path $ClassicDir ".env.template")) {
        Copy-Item (Join-Path $ClassicDir ".env.template") (Join-Path $ClassicDir ".env")
    }
}

if (Test-Path (Join-Path $Root ".env.example")) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $ClassicDir ".env") -Force
}

Write-Host "AutoGPT classic repository is ready at $ClassicDir"
Write-Host "If Poetry is installed, run .\\run.ps1 to start the CLI."
