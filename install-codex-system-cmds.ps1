$ErrorActionPreference = 'Stop'

$source = 'D:\codex\bin'
$target = 'D:\新建文件夹\bin'
$files = @(
    'codex.cmd'
    'nasm.cmd'
    'gcc.cmd'
    'ld.cmd'
    'qemu-system-i386.cmd'
    'grub-mkrescue.cmd'
    'make.cmd'
)

if (-not (Test-Path $target)) {
    New-Item -ItemType Directory -Force $target | Out-Null
}

foreach ($file in $files) {
    Copy-Item -Force (Join-Path $source $file) (Join-Path $target $file)
}

Write-Host $target
