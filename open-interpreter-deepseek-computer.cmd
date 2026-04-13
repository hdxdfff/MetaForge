@echo off
setlocal
set "OI_HOME=D:\codex\tools\python311-embed"
set "OPEN_INTERPRETER_CONFIG_DIR=D:\codex\oi-state\open-interpreter\open-interpreter"
set "OPEN_INTERPRETER_CONTRIBUTE_CACHE=D:\codex\oi-state\cache\open-interpreter\contribute.json"
"%OI_HOME%\Scripts\interpreter.exe" -y --profile computer.yaml %*
