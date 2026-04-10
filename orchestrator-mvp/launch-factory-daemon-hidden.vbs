Set shell = CreateObject("WScript.Shell")
shell.Run "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\codex\orchestrator-mvp\start-factory-daemon.ps1"" -Interval 1 -MetaEvery 5 -EvolutionEvery 3", 0, False
