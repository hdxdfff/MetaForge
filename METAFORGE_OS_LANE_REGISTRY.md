# MetaForge OS Lane Registry

This file is the local lane registry for Codex multi-session work.

## Purpose

Keep lane ownership, scope, and priorities explicit inside the main workspace.

## Rule

Each lane must define:

- dialogue id
- lane type
- target workspace
- allowed scope
- forbidden scope
- current goal
- priority
- merge policy
- workspace lock flag

## Current lanes

- `main-dialogue` as `ceo-lane`
- `toyos-product-dialogue` as `product-lane`
- `metaforge-research-dialogue` as `research-lane`
- `ops-chore-dialogue` as `chore-lane`

## Operation

Use `D:\codex\metaforge-lane-status.ps1` to build a lane workboard from this registry and the current shared memory.
