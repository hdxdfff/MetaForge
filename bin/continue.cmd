@echo off
setlocal
set "CONTINUE_CONFIG_DIR=%USERPROFILE%\.continue"
if not exist "%CONTINUE_CONFIG_DIR%" mkdir "%CONTINUE_CONFIG_DIR%" >nul 2>&1
start "" "D:\Microsoft VS Code\bin\code.cmd" "%CD%"
