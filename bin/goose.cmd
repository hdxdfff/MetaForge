@echo off
setlocal
for /f "usebackq delims=" %%K in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-Content 'D:\codex\opencode.jsonc' -Raw | ConvertFrom-Json; $cfg.provider.'volcengine-plan'.options.apiKey"`) do set "OPENAI_API_KEY=%%K"
set "GOOSE_PROVIDER=openai"
set "GOOSE_MODEL=minimax-m2.5"
set "OPENAI_HOST=http://localhost:8711"
set "OPENAI_BASE_PATH=v1/chat/completions"
"C:\Users\lenovo\.local\bin\goose.exe" %*
