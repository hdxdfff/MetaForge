param(
    [ValidateSet('ceo-lane','product-lane','research-lane','chore-lane')]
    [string]$Lane = 'ceo-lane'
)

$ErrorActionPreference = 'Stop'

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Missing file: $Path"
    }
    return Get-Content -Path $Path -Raw | ConvertFrom-Json
}

powershell -ExecutionPolicy Bypass -File 'D:\codex\metaforge-memory-snapshot.ps1' | Out-Null
powershell -ExecutionPolicy Bypass -File 'D:\codex\metaforge-lane-asset-pack.ps1' | Out-Null

$packDir = 'D:\codex\lane-assets'
$jsonPath = Join-Path $packDir ($Lane + '.json')
$mdPath = Join-Path $packDir ($Lane + '.md')
$payload = Read-JsonFile $jsonPath

$result = [ordered]@{
    status = 'ok'
    lane = $Lane
    authoritative_workspace = $payload.authoritative_workspace
    contradiction = $payload.contradiction
    ceo_priority = $payload.ceo_priority
    control_tier = $payload.control_tier
    validation = $payload.validation
    asset_json = $jsonPath
    asset_markdown = $mdPath
    startup_files = $payload.startup_files
    startup_command = $payload.startup_command
    next_action = $payload.next_action
}

$result | ConvertTo-Json -Depth 8
