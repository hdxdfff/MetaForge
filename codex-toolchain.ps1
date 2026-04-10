param(
    [switch]$ShowStatus,
    [switch]$Json,
    [switch]$Activate
)

$ErrorActionPreference = 'Stop'

$CodexRoot = 'D:\codex'
$ToolRoots = [ordered]@{
    python = Join-Path $CodexRoot 'tools\python311-embed'
    git    = Join-Path $CodexRoot 'tools\mingit-2.53.0-64-bit\mingw64\bin'
    node    = Join-Path $CodexRoot 'tools\node-v22.22.1-win-x64'
    docker  = 'C:\Program Files\Docker\Docker\resources\bin'
    system32 = Join-Path $env:WINDIR 'System32'
}

$PythonExe = Join-Path $ToolRoots.python 'python.exe'
$GitExe = Join-Path $ToolRoots.git 'git.exe'
$NodeExe = Join-Path $ToolRoots.node 'node.exe'
$DockerExe = Join-Path $ToolRoots.docker 'docker.exe'
$ManagedImage = 'toyos-managed-toolchain'
$rgProbe = Get-Command rg.exe -ErrorAction SilentlyContinue
if ($rgProbe -and $rgProbe.Source) {
    $ToolRoots.rg = $rgProbe.Source
}

$env:CODEX_ROOT = $CodexRoot
$env:DOCKER_CONFIG = Join-Path $CodexRoot 'tmp\docker-config'
$env:GIT_CONFIG_NOSYSTEM = '1'
$env:PYTHONUTF8 = '1'

New-Item -ItemType Directory -Force (Split-Path -Parent $env:DOCKER_CONFIG) | Out-Null
New-Item -ItemType Directory -Force $env:DOCKER_CONFIG | Out-Null

$pathParts = @(
    $ToolRoots.python
    $ToolRoots.git
    $ToolRoots.node
    $ToolRoots.docker
    $(if ($ToolRoots.rg) { Split-Path -Parent $ToolRoots.rg })
    $ToolRoots.system32
    $env:PATH
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

$env:PATH = ($pathParts -join ';')
Set-Location $CodexRoot

function Convert-CodexContainerPath {
    param([string]$Value)
    if (-not $Value) {
        return $Value
    }
    $normalized = $Value -replace '\\', '/'
    if ($normalized.StartsWith('D:/codex/', [System.StringComparison]::OrdinalIgnoreCase)) {
        return '/codex' + $normalized.Substring('D:/codex'.Length)
    }
    if ($normalized -eq 'D:/codex') {
        return '/codex'
    }
    return $Value
}

function Get-CodexContainerWorkdir {
    $current = (Get-Location).Path
    $normalized = $current -replace '\\', '/'
    if ($normalized.StartsWith('D:/codex/', [System.StringComparison]::OrdinalIgnoreCase)) {
        return '/codex' + $normalized.Substring('D:/codex'.Length)
    }
    if ($normalized -eq 'D:/codex') {
        return '/codex'
    }
    return '/codex'
}

function Invoke-CodexManagedTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ToolName,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    if (-not (Test-Path $DockerExe)) {
        throw "docker.exe not found at $DockerExe"
    }

    $dockerArgs = @(
        'run',
        '--rm',
        '-v', "${CodexRoot}:/codex",
        '-w', (Get-CodexContainerWorkdir),
        $ManagedImage,
        $ToolName
    )
    foreach ($arg in $Args) {
        $dockerArgs += Convert-CodexContainerPath $arg
    }

    & $DockerExe @dockerArgs
    return $LASTEXITCODE
}

function Install-CodexManagedToolAliases {
    function global:nasm {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
        Invoke-CodexManagedTool -ToolName 'nasm' @Args
    }

    function global:gcc {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
        Invoke-CodexManagedTool -ToolName 'gcc' @Args
    }

    function global:ld {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
        Invoke-CodexManagedTool -ToolName 'ld' @Args
    }

    function global:qemu-system-i386 {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
        Invoke-CodexManagedTool -ToolName 'qemu-system-i386' @Args
    }

    function global:grub-mkrescue {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
        Invoke-CodexManagedTool -ToolName 'grub-mkrescue' @Args
    }

    function global:make {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
        Invoke-CodexManagedTool -ToolName 'make' @Args
    }
}

if ($Activate) {
    Install-CodexManagedToolAliases
}

function Test-Tool {
    param([string]$Name)
    $resolved = Get-Command $Name -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        name = $Name
        resolved = [bool]$resolved
        source = if ($resolved) { $resolved.Source } else { $null }
    }
}

$report = [ordered]@{
    root = $CodexRoot
    path = @($pathParts)
    docker_config = $env:DOCKER_CONFIG
    tools = @(
        Test-Tool -Name 'python'
        Test-Tool -Name 'git'
        Test-Tool -Name 'node'
        Test-Tool -Name 'docker'
        if ($Activate) {
            Test-Tool -Name 'nasm'
            Test-Tool -Name 'gcc'
            Test-Tool -Name 'ld'
            Test-Tool -Name 'qemu-system-i386'
            Test-Tool -Name 'grub-mkrescue'
            Test-Tool -Name 'make'
        }
        if ($ToolRoots.rg) {
            [pscustomobject]@{
                name = 'rg'
                resolved = $true
                source = $ToolRoots.rg
                runnable = $false
                note = 'discovered but execution is denied in this environment'
            }
        } else {
            [pscustomobject]@{
                name = 'rg'
                resolved = $false
                source = $null
                runnable = $false
                note = 'not discovered'
            }
        }
    )
    explicit_paths = [ordered]@{
        python = $PythonExe
        git = $GitExe
        node = $NodeExe
        docker = $DockerExe
        rg = $ToolRoots.rg
    }
    managed_wrappers = if ($Activate) { @('nasm', 'gcc', 'ld', 'qemu-system-i386', 'grub-mkrescue', 'make') } else { @() }
}

if ($ShowStatus) {
    Write-Host "Codex toolchain recovery loaded." -ForegroundColor Cyan
    Write-Host "root: $CodexRoot"
    Write-Host "docker_config: $($env:DOCKER_CONFIG)"
    foreach ($tool in $report.tools) {
        $state = if ($tool.name -eq 'rg') {
            if ($tool.resolved) { 'blocked' } else { 'missing' }
        } elseif ($tool.resolved) {
            'ok'
        } else {
            'missing'
        }
        $source = if ($tool.source) { $tool.source } else { 'unresolved' }
        $suffix = if ($tool.note) { " ($($tool.note))" } else { '' }
        Write-Host ("- {0}: {1}{2}" -f $state, $source, $suffix)
    }
}

if ($Json) {
    $report | ConvertTo-Json -Depth 6
}
