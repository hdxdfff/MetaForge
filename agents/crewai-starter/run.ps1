param(
    [switch]$Install,
    [string]$ImagePath,
    [string]$Question
)

$ErrorActionPreference = "Stop"
$env:LOCALAPPDATA = "D:\codex\oi-state\localappdata"
$env:CREWAI_STORAGE_DIR = "crewai-starter"
$env:CREWAI_DB_STORAGE_PATH = "D:\codex\oi-state\crewai-data"
$env:CREWAI_CREDENTIALS_DIR = "D:\codex\oi-state\crewai-credentials"
$Python = "D:\codex\tools\python311-embed\python.exe"
$Pip = "D:\codex\tools\python311-embed\Scripts\pip.exe"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
    Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $ProjectRoot ".env")
    Write-Host "Created .env from .env.example. Fill in OPENAI_API_KEY or DASHSCOPE_API_KEY before running."
}

if ($Install) {
    & $Pip install -r (Join-Path $ProjectRoot "requirements.txt")
}

if ($ImagePath) {
    if ($Question) {
        & $Python (Join-Path $ProjectRoot "vision_demo.py") $ImagePath $Question
    }
    else {
        & $Python (Join-Path $ProjectRoot "vision_demo.py") $ImagePath
    }
}
else {
    & $Python (Join-Path $ProjectRoot "main.py")
}
