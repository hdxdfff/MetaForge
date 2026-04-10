$ErrorActionPreference = 'Stop'

$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$env:Path = $machinePath

Write-Host "Machine PATH has codex bin: " -NoNewline
Write-Host ($machinePath -like '*D:\新建文件夹\bin*')

Write-Host "where codex:"
where.exe codex
Write-Host "where nasm:"
where.exe nasm
Write-Host "where gcc:"
where.exe gcc
Write-Host "where ld:"
where.exe ld
Write-Host "where qemu-system-i386:"
where.exe qemu-system-i386
Write-Host "where grub-mkrescue:"
where.exe grub-mkrescue
Write-Host "where make:"
where.exe make
