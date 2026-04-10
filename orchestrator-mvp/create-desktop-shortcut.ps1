$WshShell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$target = 'D:\codex\orchestrator-mvp\dist\AICommandConsole\AICommandConsole.exe'
$workdir = 'D:\codex\orchestrator-mvp\dist\AICommandConsole'
$icon = 'D:\codex\orchestrator-mvp\assets\AICommandConsole.ico'
$shortcut = $WshShell.CreateShortcut((Join-Path $desktop 'AI Command Console.lnk'))
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $workdir
$shortcut.Description = 'AI Engineering Command Console'
if (Test-Path $icon) {
    $shortcut.IconLocation = "$icon,0"
}
$shortcut.Save()
