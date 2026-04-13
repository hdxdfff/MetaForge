@echo off
REM Start Background Auto-Fix Daemon for MetaForge OS
REM This launches the auto-fix daemon in the background

cd /d D:\codex

echo Starting Background Auto-Fix Daemon...
echo Log file: D:\codex\workflows\auto_fix_daemon.log
echo PID file: D:\codex\workflows\auto_fix_daemon.pid

REM Start the daemon in the background using start command
start /B python.exe workflows\auto_fix_daemon.py

echo.
echo Daemon started. Check the log file for status.
echo To stop the daemon, run: taskkill /F /IM python.exe
echo.
pause
