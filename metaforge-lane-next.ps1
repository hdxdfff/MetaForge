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

$pack = Read-JsonFile 'D:\codex\METAFORGE_OS_LANE_TASK_PACKS.json'
$laneMeta = Read-JsonFile ('D:\codex\lane-assets\' + $Lane + '.json')
$laneTasks = $pack.$Lane

$result = [ordered]@{
    lane = $Lane
    authoritative_workspace = $laneMeta.authoritative_workspace
    control_tier = $laneMeta.control_tier
    validation = $laneMeta.validation
    contradiction = $laneMeta.contradiction
    ceo_priority = $laneMeta.ceo_priority
    focus = $laneTasks.focus
    tasks = $laneTasks.tasks
    startup_command = $laneMeta.startup_command
    asset_markdown = 'D:\codex\lane-assets\' + $Lane + '.md'
    asset_json = 'D:\codex\lane-assets\' + $Lane + '.json'
}

$result | ConvertTo-Json -Depth 8
