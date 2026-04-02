# Build Environments

## Overview

XCC is developed on macOS (Apple silicon). Linux/ELF builds are executed in Docker to keep the toolchain isolated and reproducible.

## macOS (native)

- The current native backend lowers directly to AArch64 assembly.
- Assembly and linking are currently delegated to the platform `clang` toolchain.
- Native Mach-O object emission is part of the compiler roadmap.

## Linux/ELF (Docker)

- Linux/ELF support is developed and validated in Docker.
- Docker images are used for compiler and toolchain validation.
- Target linker: mold.
- Target C library variants: glibc and musl.

## Docker workflow

Use the provided scripts to build and run containers:

- Build glibc image: `./scripts/docker-build.sh glibc`
- Build musl image: `./scripts/docker-build.sh musl`
- Run a command directly: `./scripts/docker-run.sh glibc <command> [args...]`
- Open a shell: `./scripts/docker-shell.sh glibc`
- Run tests via tox-docker: `tox -e docker_glibc` or `tox -e docker_musl`

Example test run:

- `./scripts/docker-run.sh glibc python3 -m unittest discover -v`

Note: These images are intentionally minimal and do not install tox.
