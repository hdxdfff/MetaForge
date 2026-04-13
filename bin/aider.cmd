@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PATH=D:\codex\tools\mingit-2.53.0-64-bit\cmd;%PATH%"
for /f "usebackq delims=" %%K in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-Content 'D:\codex\opencode.jsonc' -Raw | ConvertFrom-Json; $cfg.provider.'volcengine-plan'.options.apiKey"`) do set "AIDER_OPENAI_API_KEY=%%K"
set "AIDER_OPENAI_API_BASE=http://localhost:8711/v1"
set "AIDER_MODEL=openai/minimax-m2.5"
"C:\Users\lenovo\AppData\Roaming\Python\Python311\Scripts\aider.exe" --model openai/minimax-m2.5 %*
