# XCC

XCC is a C compiler written in modern Python (CPython and PyPy, 3.11+). The first target platform is macOS on Apple silicon (`arm64`). The long term goal is to compile the CPython source tree without third party runtime dependencies.

## Status

Research and scaffolding. The codebase is being prepared with strict quality and testing requirements.

## Motivation

CPython depends on a C compiler with predictable semantics and diagnostics. XCC aims to provide a clean, fully testable implementation in Python, with a focus on correctness, transparency, and reproducibility.

## Goals

- Implement a C11 compiler with clear, deterministic behavior.
- Compile the CPython source tree without modifying CPython sources.
- Zero third party runtime dependencies.
- Full test coverage with strict linting and type checking.
- Link with the mold linker for ELF targets.
- Support glibc and musl as the initial C library targets.

## Non-goals (initial)

- C++ support.
- Multiple platform backends at launch.
- A custom linker.

## Pipeline

1. Driver and source management.
2. Preprocessing and macro expansion.
3. Lexing and parsing into an AST.
4. Semantic analysis and type checking.
5. IR construction and optimization.
6. Code generation and object emission.
7. Linker integration and final artifacts.

## Design principles

- Correctness before optimization.
- Deterministic output for identical inputs.
- Small, explicit modules with minimal coupling.
- Every diagnostic path is covered by tests.

## Planned feature coverage

This is a target list for the initial milestones. It will evolve as CPython compilation uncovers gaps.

- C11 core language features required by CPython.
- Preprocessor with full macro expansion and include handling.
- Diagnostics with source ranges and stable error codes.

## Requirements

- Python 3.11+ on CPython or PyPy.
- macOS on Apple silicon (`arm64`) for the initial target.
- Docker is required to build Linux/ELF targets on macOS.
- Linux targets use the mold linker and a glibc or musl userland.

## Targets

- Native host: macOS `arm64` with Mach-O output and the system linker.
- Linux/ELF: built in Docker, linked with mold, validated against glibc and musl.

## Quality gates

- Linting: `ruff`.
- Typing: `ty`.
- Tests: `tox` + `unittest`.
- Coverage: 100% line and branch coverage; error paths must be exercised.
- Coverage tooling: `coverage` with a 100% fail-under threshold.

## Licensing constraints

- Do not copy, translate, or derive from GPL-licensed code (including tests).
- Prefer official specifications and permissively-licensed references.
- External specifications cached under `docs/_sources/` are for local reading only and must not be committed.

## Development

- Install dev tools: `uv sync --dev`
- Run lint: `tox -e lint`
- Run type checks: `tox -e type`
- Run tests: `tox -e py311`
- Run tests in Linux containers: `tox -e docker_glibc` or `tox -e docker_musl`
- Build Linux/ELF image (glibc): `./scripts/docker-build.sh glibc`
- Build Linux/ELF image (musl): `./scripts/docker-build.sh musl`
- Run a command in glibc image: `./scripts/docker-run.sh glibc <command> [args...]`
- Run a command in musl image: `./scripts/docker-run.sh musl <command> [args...]`

## Documentation

Project documentation is built with MkDocs and lives in `docs/`.
