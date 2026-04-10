$ErrorActionPreference = 'Stop'

$env:Path = 'D:\新建文件夹\bin\;C:\Windows\System32'
Write-Host "PATH=$env:Path"
where.exe codex
where.exe nasm
