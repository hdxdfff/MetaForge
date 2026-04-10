@echo off
setlocal
set "PATH=D:\codex\tools\mingit-2.53.0-64-bit\cmd;%PATH%"
set "PLANDEX_ENV=development"
set "PLANDEX_API_HOST=http://localhost:8099"
set "PLANDEX_HOME=%USERPROFILE%\.plandex-home-dev-v2"
if not exist "%PLANDEX_HOME%" mkdir "%PLANDEX_HOME%" >nul 2>&1
"D:\codex\bin\plandex.exe" %*
