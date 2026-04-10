$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$embedded = Join-Path $root "..\tools\python311-embed\python.exe"
$bootstrap = Join-Path $root "bootstrap_runner.py"
$icon = Join-Path $root "assets\AICommandConsole.ico"

if (-not (Test-Path $embedded)) {
    throw "Missing embedded Python runtime: $embedded"
}

if (-not (Test-Path $icon)) {
    throw "Missing application icon: $icon"
}

& $embedded $bootstrap -m PyInstaller --noconfirm --windowed --name AICommandConsole --icon $icon --add-data "app;app" --add-data "tools;tools" --add-data ".env.example;." --add-data "assets;assets" desktop_app.py
