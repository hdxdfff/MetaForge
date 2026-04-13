$ErrorActionPreference = 'Stop'

$entries = @(
    'D:\codex\bin'
    'D:\codex\tools\python311-embed'
    'D:\codex\tools\mingit-2.53.0-64-bit\mingw64\bin'
    'D:\codex\tools\node-v22.22.1-win-x64'
)

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @()
if ($userPath) {
    $parts += $userPath -split ';'
}
foreach ($entry in $entries) {
    if ($parts -notcontains $entry) {
        $parts += $entry
    }
}

$newPath = ($parts -join ';').Trim(';')
[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
$env:Path = $newPath + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')

Write-Host $newPath
