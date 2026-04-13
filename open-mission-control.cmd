@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "URL=http://127.0.0.1:8787/"
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "PROFILE=%TEMP%\codex-mission-control-profile"
set "API_STARTER=D:\codex\orchestrator-mvp\run-api.cmd"
set "BOOTSTRAP=http://127.0.0.1:8787/api/bootstrap"
set "ORCH_NETWORK_AGENT_ENABLED=false"

if not exist "%CHROME%" (
  echo Chrome not found: %CHROME%
  echo Open this URL manually:
  echo %URL%
  exit /b 1
)

for /f %%A in ('powershell -NoProfile -Command "try { (Invoke-WebRequest ''%BOOTSTRAP%'' -TimeoutSec 2 -UseBasicParsing).StatusCode ^| Out-Null; Write-Output up } catch { Write-Output down }"') do set "HEALTH=%%A"
for /f %%A in ('curl.exe --noproxy 127.0.0.1 -sS --max-time 2 -o NUL -w "%%{http_code}" "%BOOTSTRAP%" 2^>nul') do set "HEALTH_CODE=%%A"
if /i not "%HEALTH_CODE%"=="200" (
  powershell -NoProfile -Command "Get-CimInstance Win32_Process ^| Where-Object { $_.CommandLine -match 'serve_api\.py|serve_backend\.py' -and $_.CommandLine -match 'orchestrator-mvp' } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
  if exist "%API_STARTER%" (
    start "" /b "%API_STARTER%"
    for /L %%I in (1,1,10) do (
      set "HEALTH_CODE="
      for /f %%B in ('curl.exe --noproxy 127.0.0.1 -sS --max-time 2 -o NUL -w "%%{http_code}" "%BOOTSTRAP%" 2^>nul') do set "HEALTH_CODE=%%B"
      if "!HEALTH_CODE!"=="200" goto :launch_browser
      timeout /t 1 /nobreak >nul
    )
  )
)

if not exist "%PROFILE%" mkdir "%PROFILE%" >nul 2>&1

:launch_browser
start "" "%CHROME%" ^
  --new-window ^
  --user-data-dir="%PROFILE%" ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-extensions ^
  --no-proxy-server ^
  --proxy-bypass-list="<-loopback>" ^
  --disable-background-networking ^
  --app="%URL%"
