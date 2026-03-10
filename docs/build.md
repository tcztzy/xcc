# Build Environments

## Overview

XCC is developed on macOS (Apple silicon). Linux/ELF builds are executed in Docker to keep the toolchain isolated and reproducible.

## macOS (native)

- The preview native backend lowers directly to AArch64 assembly.
- Assembly and linking are delegated to the platform `clang` toolchain.
- Standalone Mach-O object emission is not shipped in this preview.

## Linux/ELF (Docker)

- Linux/ELF remains a validation target, not a shipped native backend.
- Docker images are used for frontend and toolchain validation.
- Planned linker target: mold.
- Planned C library targets: glibc and musl.

## Docker workflow

Use the provided scripts to build and run containers:

- Build glibc image: `./scripts/docker-build.sh glibc`
- Build musl image: `./scripts/docker-build.sh musl`
- Run a command directly: `./scripts/docker-run.sh glibc <command> [args...]`
- Open a shell: `./scripts/docker-shell.sh glibc`
- Run tests via tox-docker: `tox -e docker_glibc` or `tox -e docker_musl`

Example test run:

- `./scripts/docker-run.sh glibc python -m unittest discover -v`

Note: These images are intentionally minimal and do not install tox.
