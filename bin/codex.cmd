@echo off
if /I "%~1"=="app" (
  shift
  call "E:\codex\start-codex-app-account.bat" app %*
  exit /b %errorlevel%
)
call "E:\codex\start-codex.bat" %*
