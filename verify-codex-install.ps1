$ErrorActionPreference = 'Stop'

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$combined = @()
if ($machinePath) { $combined += $machinePath -split ';' }
if ($userPath) { $combined += $userPath -split ';' }

$checks = [ordered]@{
    user_path_has_bin = $combined -contains 'D:\codex\bin'
    user_path_has_python = $combined -contains 'D:\codex\tools\python311-embed'
    user_path_has_git = $combined -contains 'D:\codex\tools\mingit-2.53.0-64-bit\mingw64\bin'
    user_path_has_node = $combined -contains 'D:\codex\tools\node-v22.22.1-win-x64'
    machine_path_has_system_bin = $combined -contains 'D:\新建文件夹\bin'
}

Write-Host "PATH checks:"
foreach ($entry in $checks.GetEnumerator()) {
    Write-Host ("- {0}: {1}" -f $entry.Key, $entry.Value)
}

Write-Host "System shim directory:"
Get-ChildItem 'D:\新建文件夹\bin' -Filter '*.cmd' | Select-Object Name,Length | Format-Table -AutoSize | Out-String | Write-Host

$env:Path = ($combined -join ';')
Write-Host "where codex:"
where.exe codex
Write-Host "where nasm:"
where.exe nasm

Write-Host "Wrapper check: nasm.cmd --version"
& 'D:\codex\bin\nasm.cmd' --version
Write-Host "Wrapper check: gcc.cmd --version"
& 'D:\codex\bin\gcc.cmd' --version | Select-Object -First 1
