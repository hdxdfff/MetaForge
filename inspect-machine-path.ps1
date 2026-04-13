$ErrorActionPreference = 'Stop'

$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$segments = $machinePath -split ';'

Write-Host "COUNT=$($segments.Count)"
Write-Host "FIRST_SEGMENTS:"
$segments | Select-Object -First 12 | ForEach-Object { Write-Host $_ }
Write-Host "HAS_SYSTEM_BIN=$($segments -contains 'D:\新建文件夹\bin')"
