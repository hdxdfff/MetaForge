Set shell = CreateObject("WScript.Shell")
shell.Run "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\codex\orchestrator-mvp\run-release-manager.ps1""", 0, False
