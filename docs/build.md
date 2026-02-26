# Build Environments

## Overview

XCC is developed on macOS (Apple silicon). Linux/ELF builds are executed in Docker to keep the toolchain isolated and reproducible.

## macOS (native)

- Output format: Mach-O.
- Linker: system linker (ld64 via the platform toolchain).

## Linux/ELF (Docker)

- Output format: ELF.
- Linker: mold.
- C library targets: glibc and musl.

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
