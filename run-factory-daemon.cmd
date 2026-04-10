@echo off
setlocal
set "ROOT=D:\codex\orchestrator-mvp"
set "PYTHONEXE=D:\codex\tools\python311-embed\python.exe"
set "DAEMON_SCRIPT=%ROOT%\tools\factory_daemon.py"
"%PYTHONEXE%" "%DAEMON_SCRIPT%" --interval 1 --meta-every 5 --evolution-every 10
exit /b %ERRORLEVEL%
