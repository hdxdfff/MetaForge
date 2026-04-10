param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Action,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

switch ($Action.ToLowerInvariant()) {
    "bridge" {
        & "$PSScriptRoot\vm-bridge.cmd" @Args
        exit $LASTEXITCODE
    }
    "check" {
        & "$PSScriptRoot\vm-check.cmd" @Args
        exit $LASTEXITCODE
    }
    "ssh" {
        & "$PSScriptRoot\vm-ssh.cmd" @Args
        exit $LASTEXITCODE
    }
    "exec" {
        & "$PSScriptRoot\vm-ssh.cmd" @Args
        exit $LASTEXITCODE
    }
    "script" {
        & "$PSScriptRoot\vm-ssh.cmd" -ScriptPath @Args
        exit $LASTEXITCODE
    }
    "plink" {
        & "$PSScriptRoot\vm-plink.cmd" @Args
        exit $LASTEXITCODE
    }
    "run" {
        & "$PSScriptRoot\vm-run.cmd" @Args
        exit $LASTEXITCODE
    }
    "doctor" {
        & "$PSScriptRoot\vm-check.cmd" @Args
        exit $LASTEXITCODE
    }
    "put" {
        & "$PSScriptRoot\vm-put.cmd" @Args
        exit $LASTEXITCODE
    }
    "get" {
        & "$PSScriptRoot\vm-get.cmd" @Args
        exit $LASTEXITCODE
    }
    "pdf" {
        & "$PSScriptRoot\vm-pandoc-pdf-zh.cmd" @Args
        exit $LASTEXITCODE
    }
    "help" {
        @"
Usage:
  vmctl.cmd bridge
  vmctl.cmd check
  vmctl.cmd doctor
  vmctl.cmd ssh <remote command...>
  vmctl.cmd exec <remote command...>
  vmctl.cmd ssh -CommandString "<exact remote command>"
  vmctl.cmd ssh -ScriptPath D:\codex\tools\script.sh
  vmctl.cmd script D:\codex\tools\script.sh
  vmctl.cmd plink <remote command...>
  vmctl.cmd run <guest command...>
  vmctl.cmd put <host path> <guest path>
  vmctl.cmd get <guest path> <host path>
  vmctl.cmd pdf <input.md> <output.pdf> [extra pandoc args...]
"@ | Write-Output
        exit 0
    }
    default {
        throw "Unknown action '$Action'. Use: check, ssh, run, put, get, pdf, help."
    }
}
