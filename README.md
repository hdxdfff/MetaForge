# MetaForge

MetaForge is a local-first control plane for multi-agent operations and agent experimentation. It brings together orchestration workflows, runtime tooling, operational knowledge, and generated demonstrations in one workspace.

## What is here

- `orchestrator-mvp/` — orchestration and runtime control logic.
- `knowledge/` and `goals/` — machine-readable operational context and goal state.
- `workflows/` and `skills/` — repeatable operator and engineering playbooks.
- `generated/` — generated deliverables and demonstrations, including ToyOS artifacts.
- `tools/` — local helper tools and portable runtimes used by the workspace.

## Project status

MetaForge is an experimental, actively evolving workspace. Interfaces and internal layout may change while the control-plane workflow is refined.

## Backup and release policy

This public repository is for source, documentation, and reproducible project artifacts. It is not a backup download portal.

Operational archives, environment snapshots, manifests containing private context, and other backup material must be stored only in a separate **private** backup repository or private storage. Do not attach such material to GitHub Releases in this public repository: releases and their assets are public whenever the repository is public.

The former public backup release has been removed. The historical backup notes under `backups/` are retained only as repository context and must not be used as restore instructions.

## Working with the repository

Review the documentation and workflow files relevant to the subsystem you are changing before running an operation. Changes should be validated in the target runtime environment and must not introduce credentials, private archives, or generated secrets into Git history.

## License

No repository-wide open-source license has been selected yet. The workspace also contains bundled and third-party components with their own licensing terms; do not assume a blanket license applies.
