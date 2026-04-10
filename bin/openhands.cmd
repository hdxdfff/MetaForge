@echo off
setlocal
if /I "%~1"=="-h" goto :help
if /I "%~1"=="--help" goto :help
set "OPENHANDS_HOME=%USERPROFILE%\.openhands"
if not exist "%OPENHANDS_HOME%" mkdir "%OPENHANDS_HOME%" >nul 2>&1
set "OPENHANDS_CONFIG=D:\codex\openhands.config.toml"
set "OPENHANDS_SECRET_FILE=D:\codex\openhands.secret.key"
if not exist "%OPENHANDS_SECRET_FILE%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); [Convert]::ToBase64String($bytes) | Set-Content -NoNewline '%OPENHANDS_SECRET_FILE%'"
)
for /f "usebackq delims=" %%K in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content 'D:\codex\openhands.secret.key' -Raw"`) do set "OH_SECRET_KEY=%%K"
set "OH_PERSISTENCE_DIR=/.openhands"
for /f "usebackq delims=" %%K in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-Content 'D:\codex\opencode.jsonc' -Raw | ConvertFrom-Json; $cfg.provider.'volcengine-plan'.options.apiKey"`) do set "LLM_API_KEY=%%K"
set "LLM_MODEL=openai/minimax-m2.5"
set "LLM_BASE_URL=http://host.docker.internal:8711/v1"
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" rm -f openhands-app >nul 2>&1
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" run --rm --pull=always -i -e NO_SETUP=true -e SANDBOX_USER_ID=0 -e WORKSPACE_BASE=/opt/workspace -e LLM_API_KEY=%LLM_API_KEY% -e LLM_MODEL=%LLM_MODEL% -e LLM_BASE_URL=%LLM_BASE_URL% -e OH_SECRET_KEY=%OH_SECRET_KEY% -v /var/run/docker.sock:/var/run/docker.sock -v "%OPENHANDS_HOME%:/.openhands" -v "%OPENHANDS_CONFIG%:/app/config.toml:ro" -v "%CD%:/opt/workspace" -p 3000:3000 --add-host host.docker.internal:host-gateway --name openhands-app docker.openhands.dev/openhands/openhands:1.5 %*
goto :eof

:help
echo OpenHands launches a local server at http://localhost:3000
echo The current workspace is mounted into the container and the server uses the local LLM gateway.
echo Usage: openhands.cmd [server args]
