@echo off
REM Background Auto-Fix Runner for MetaForge OS
REM This batch file runs the auto-fix workflow in the background

cd /d D:\codex

echo [%date% %time%] Starting background auto-fix workflow... >> workflows\auto_fix_bg.log

:loop
python workflows\background_auto_fix.py >> workflows\auto_fix_bg.log 2>&1
echo [%date% %time%] Auto-fix cycle completed. Waiting 60 seconds... >> workflows\auto_fix_bg.log
timeout /t 60 /nobreak >nul
goto loop
