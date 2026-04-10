# MetaForge OS Lane Asset Pack Model

This file defines how dialogue assets should be specialized per lane.

## Goal

Turn one shared dialogue asset into multiple lane-ready startup packs.

## Lane asset types

- `ceo-lane`: arbitration, routing integrity, dispatch approval
- `product-lane`: bounded product delivery
- `research-lane`: policy, KPI, memory, self-improvement
- `chore-lane`: summaries, inventories, reports, formatting work

## Shared fields

Every lane asset should include:

- lane name
- authoritative workspace
- current contradiction
- CEO priority
- control tier
- validation requirement
- startup files
- startup command
- next action

## Lane-specific emphasis

### CEO lane

Emphasize:

- route drift
- active execution roots
- invalid delivery risk
- dispatch approval role

### Product lane

Emphasize:

- product workspace
- product-specific constraints
- allowed artifact types
- verification requirements

### Research lane

Emphasize:

- policy docs
- KPI docs
- routing and memory issues
- self-improvement targets

### Chore lane

Emphasize:

- report-only or low-risk artifacts
- chore-only control tier
- lightweight validation

## Rule

A fresh dialogue should prefer a lane-specific asset pack over a generic handoff when one exists.
