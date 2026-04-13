@echo off
setlocal

set "CODEX_ROOT=%~dp0"
"%CODEX_ROOT%tools\python311-embed\python.exe" "%CODEX_ROOT%tools\workspace_backup.py" %*
