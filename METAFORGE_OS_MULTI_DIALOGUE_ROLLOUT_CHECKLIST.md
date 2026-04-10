# Multi-Dialogue Rollout Checklist

## Phase 0

- self model present
- state model present
- world model present
- CEO view present

## Phase 1

- add lane registry
- define lane ids
- define target workspaces
- define merge policies

## Phase 2

- add lane-aware dispatch fields
- enable `workspace_locked`
- prevent provider workspace override for locked lanes

## Phase 3

- run two concurrent dialogues with distinct scopes
- verify no overlap corruption
- verify provider-only output is rejected

## Phase 4

- add promotion gate
- add conflict queueing
- add lane-local to shared-state promotion rules

## Go/No-Go checks

Go only if:

- target workspace integrity is preserved
- route drift is visible in CEO state
- invalid delivery is rejected
- product lane remains productive during platform proposal work
