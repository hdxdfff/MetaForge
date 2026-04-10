@echo off
setlocal
set "VMCTL=D:\codex\vm-entry-root\vmctl.cmd"

if "%~1"=="" goto :help
set "action=%~1"
shift

if /I "%action%"=="check" goto :dispatch
if /I "%action%"=="doctor" goto :dispatch
if /I "%action%"=="bridge" goto :dispatch
if /I "%action%"=="ssh" goto :dispatch
if /I "%action%"=="exec" goto :dispatch
if /I "%action%"=="script" goto :dispatch
if /I "%action%"=="plink" goto :dispatch
if /I "%action%"=="run" goto :dispatch
if /I "%action%"=="put" goto :dispatch
if /I "%action%"=="get" goto :dispatch
if /I "%action%"=="pdf" goto :dispatch
if /I "%action%"=="help" goto :help

echo Unknown action "%action%".
goto :help_fail

:dispatch
call "%VMCTL%" %action% %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:help
call "%VMCTL%" help
exit /b %errorlevel%

:help_fail
call "%VMCTL%" help
exit /b 1
