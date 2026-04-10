@echo off
setlocal
set "VM_ROOT=%~dp0"

if "%~1"=="" goto :help
set "action=%~1"
shift

if /I "%action%"=="check" goto :check
if /I "%action%"=="doctor" goto :check
if /I "%action%"=="ssh" goto :ssh
if /I "%action%"=="exec" goto :ssh
if /I "%action%"=="script" goto :script
if /I "%action%"=="plink" goto :plink
if /I "%action%"=="run" goto :run
if /I "%action%"=="put" goto :put
if /I "%action%"=="get" goto :get
if /I "%action%"=="pdf" goto :pdf
if /I "%action%"=="help" goto :help

echo Unknown action "%action%".
goto :help_fail

:check
call "%VM_ROOT%vm-check.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:ssh
call "%VM_ROOT%vm-ssh.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:script
call "%VM_ROOT%vm-ssh.cmd" -ScriptPath %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:plink
call "%VM_ROOT%vm-plink.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:run
call "%VM_ROOT%vm-run.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:put
call "%VM_ROOT%vm-put.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:get
call "%VM_ROOT%vm-get.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:pdf
call "%VM_ROOT%vm-pandoc-pdf-zh.cmd" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:help
echo Usage:
echo   vmctl.cmd check
echo   vmctl.cmd doctor
echo   vmctl.cmd ssh ^<remote command...^>
echo   vmctl.cmd exec ^<remote command...^>
echo   vmctl.cmd ssh -CommandString "^<exact remote command^>"
echo   vmctl.cmd ssh -ScriptPath E:\codex\tools\script.sh
echo   vmctl.cmd script E:\codex\tools\script.sh
echo   vmctl.cmd plink ^<remote command...^>
echo   vmctl.cmd run ^<guest command...^>
echo   vmctl.cmd put ^<host path^> ^<guest path^>
echo   vmctl.cmd get ^<guest path^> ^<host path^>
echo   vmctl.cmd pdf ^<input.md^> ^<output.pdf^> [extra pandoc args...]
exit /b 0

:help_fail
call :help
exit /b 1
