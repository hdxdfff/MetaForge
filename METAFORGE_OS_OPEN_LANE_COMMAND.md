# MetaForge OS Open Lane Command

This file defines the unified command for opening a fresh lane-ready dialogue context.

## Goal

Allow the main dialogue to select a lane and immediately obtain the correct handoff asset.

## Supported lanes

- `ceo-lane`
- `product-lane`
- `research-lane`
- `chore-lane`

## Behavior

The command should:

1. refresh shared memory if needed
2. refresh lane asset packs if needed
3. select the requested lane asset
4. return the lane pack path and startup instructions

## Output

The output should include:

- lane
- authoritative workspace
- control tier
- validation requirement
- asset paths
- startup command

## Rule

Opening a lane does not itself authorize execution.
It only prepares a fresh bounded starting context.
