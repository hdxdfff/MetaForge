# MetaForge OS Docker and VMware Reuse Template

This document defines a portable contract that other systems can reuse when they want:

- `Docker` for repeatable builds, packaging, and controlled test execution
- `VMware` for full guest-OS validation, boot-chain checks, and long-run runtime observation

The rule is simple:

- use `Docker` to make the toolchain deterministic
- use `VMware` to make the runtime environment representative

## Division of labor

### Docker

Use Docker as the build sandbox when the task needs:

- compiler and linker isolation
- reproducible package installation
- controlled filesystem layout
- scripted artifact generation
- cheap, frequent validation

Recommended responsibilities:

- compile source
- link binaries
- produce ISO or disk images
- run unit or smoke tests that do not need a real boot chain
- emit machine-readable build reports

### VMware

Use VMware when the task needs:

- full firmware and boot-loader behavior
- guest kernel startup validation
- realistic device enumeration
- manual inspection of guest output
- longer soak runs inside a real VM

Recommended responsibilities:

- boot the produced image
- verify the guest reaches the expected kernel stage
- capture serial or screen output
- run long-duration runtime checks
- report boot success, reset loops, hangs, or panics

## Reuse contract

Any system that wants to reuse both tools should expose the same four inputs and four outputs.

### Inputs

- source tree path
- target architecture
- build profile
- VM profile

### Outputs

- build artifact path
- runtime artifact path
- test report path
- failure summary path

## Recommended workspace layout

```text
project/
  Dockerfile.build
  build.sh
  build.ps1
  vm/
    vmware-profile.json
    vmware-run.sh
    vmware-run.ps1
  reports/
    build-report.json
    vm-report.json
  artifacts/
```

## Docker side contract

The Docker side should:

1. mount the source tree into a fixed container path
2. install the toolchain in the image or derive it from a pinned base image
3. run a single entrypoint command for build or test
4. write outputs to a fixed artifact directory
5. return a nonzero exit code on any compile, link, or packaging failure

Suggested command shape:

```text
docker run --rm -v <host-root>:/work -w /work <image> <command>
```

## VMware side contract

The VMware side should:

1. boot a prebuilt image or ISO
2. expose serial output to the host
3. keep the guest profile fixed for repeatability
4. stop on timeout, panic, or reboot loop
5. write a VM transcript and a structured result file

Suggested command shape:

```text
vmware <profile> -> boot image -> capture serial log -> emit vm-report.json
```

## Standard manifest

Each system should emit one small manifest that records the same fields:

- `target`
- `toolchain`
- `build_ready`
- `build_success`
- `runtime_ready`
- `runtime_success`
- `artifact_paths`
- `notes`

This keeps different projects comparable even when their internals differ.

## Integration steps for a new system

1. Define the build image and pin its base image.
2. Define the VMware guest profile and pin its hardware assumptions.
3. Add one build entrypoint that runs inside Docker.
4. Add one run entrypoint that launches the VMware profile.
5. Write one report file for build results and one for VM results.
6. Document the exact host prerequisites and failure modes.

## Failure modes to expect

- Docker image pull failure
- missing compiler or linker in the build image
- VMware boot failure because the guest image is malformed
- guest panic after the boot loader hands off
- timeout during long-run runtime validation

## Practical rule

If a step is supposed to be reproducible, put it in Docker.
If a step is supposed to validate guest behavior, put it in VMware.
If a step needs both, split it into a Docker build stage and a VMware execution stage.
