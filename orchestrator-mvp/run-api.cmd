@echo off
cd /d D:\codex\orchestrator-mvp
if not exist ".env" copy ".env.example" ".env" >nul
D:\codex\tools\python311-embed\python.exe D:\codex\orchestrator-mvp\serve_api.py
