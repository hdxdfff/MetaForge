$ErrorActionPreference = 'Stop'

$entries = @(
    'D:\codex\bin'
    'D:\codex\tools\python311-embed'
    'D:\codex\tools\mingit-2.53.0-64-bit\mingw64\bin'
    'D:\codex\tools\node-v22.22.1-win-x64'
)

$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$parts = @()
if ($machinePath) {
    $parts += $machinePath -split ';'
}
foreach ($entry in $entries) {
    if ($parts -notcontains $entry) {
        $parts += $entry
    }
}

$newPath = ($parts -join ';').Trim(';')
[Environment]::SetEnvironmentVariable('Path', $newPath, 'Machine')
Write-Host $newPath
