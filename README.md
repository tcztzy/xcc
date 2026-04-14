# XCC

XCC is a C compiler written in modern Python (CPython and PyPy, 3.11+). It targets a complete, deterministic, zero-runtime-dependency C11 compiler, with macOS on Apple silicon (`arm64`) as the primary native development platform today and CPython compilation as a long-term compatibility target.

## Status

Alpha (`0.2.0a1`).

- Frontend validation runs for every C compile before backend selection.
- `xcc source.c` is driver mode: it validates with XCC, then uses the native backend or delegates to `clang`.
- `xcc --frontend source.c` forces a frontend-only check run.
- `--backend=auto` prefers the native macOS `arm64` backend and falls back to `clang` when native code generation is unsupported.
- `--backend=xcc` keeps native code generation strict.
- `--backend=clang` always delegates code generation and linking to `clang` after XCC frontend validation.

Current implementation still relies on the platform toolchain for assembly and linking, and full native object generation plus full-tree CPython compilation remain open work.

## Motivation

XCC aims to provide a clean, fully testable implementation in Python, with a focus on correctness, transparency, and reproducibility. CPython remains a useful long-term compatibility benchmark rather than a standing day-to-day gate.

## Goals

- Implement a complete C11 compiler with clear, deterministic behavior.
- Long-term: compile the CPython source tree without modifying CPython sources.
- Zero third party runtime dependencies.
- Full test coverage with strict linting and type checking.
- Support native code generation on macOS `arm64` and Linux/ELF.
- Keep diagnostics, testing, and behavior reproducible across host environments.

## Pipeline

1. Driver and source management.
2. Preprocessing and macro expansion.
3. Lexing and parsing into an AST.
4. Semantic analysis and type checking.
5. Direct lowering from sema AST to AArch64 assembly on macOS `arm64`.
6. Assembly, object creation, and linking via the platform `clang` toolchain.

Ongoing work includes broader native code generation, native object emission, and Linux/ELF support.

## Design principles

- Correctness before optimization.
- Deterministic output for identical inputs.
- Small, explicit modules with minimal coupling.
- Every diagnostic path is covered by tests.

## Planned feature coverage

This is a target list for the compiler roadmap. It will evolve as compiler development and Clang conformance work uncover gaps.

- C11 core language features needed for real-world codebases, including long-term CPython compatibility.
- Preprocessor with full macro expansion and include handling.
- Diagnostics with source ranges and stable error codes.

## Requirements

- Python 3.11+ on CPython or PyPy.
- macOS on Apple silicon (`arm64`) for native development today.
- Docker is required to build Linux/ELF targets on macOS.
- Linux targets use the mold linker and a glibc or musl userland.

## Current implementation

- XCC runs preprocessing, lexing, parsing, and semantic analysis for every C compile input.
- XCC can generate native AArch64 assembly on macOS `arm64` for the subset currently implemented in the backend.
- `clang` remains the assembler, linker, and code-generation fallback while native coverage expands.
- Linux/ELF validation runs in Docker and remains part of the compiler roadmap.

## CLI

- `xcc source.c` validates with XCC, then tries the native backend on macOS `arm64` and falls back to `clang` when needed.
- `xcc --frontend source.c` runs only preprocessing, lexing, parsing, and semantic analysis.
- `xcc --backend=xcc -S source.c -o -` prints native AArch64 assembly and fails on unsupported constructs.
- `xcc --backend=clang -c source.c -o source.o` validates with XCC and always compiles with `clang`.
- `xcc --no-backend-fallback source.c` keeps `auto` mode strict for backend diagnostics.

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
- Run curated Clang fixtures: `tox -e clang_suite`
- Run curated Clang fixtures directly: `XCC_RUN_CLANG_SUITE=1 python3 -m unittest -v tests.test_clang_suite`
- Run native smoke tests: `tox -e native_smoke`
- Build Python package artifacts: `uv build`
- Run tests in Linux containers: `tox -e docker_glibc` or `tox -e docker_musl`
- Build Linux/ELF image (glibc): `./scripts/docker-build.sh glibc`
- Build Linux/ELF image (musl): `./scripts/docker-build.sh musl`
- Run a command in glibc image: `./scripts/docker-run.sh glibc <command> [args...]`
- Run a command in musl image: `./scripts/docker-run.sh musl <command> [args...]`

## External fixture policy

- External archives (LLVM/Clang tarballs and cached specs) must not be committed.
- Curated LLVM fixtures are pinned in `tests/external/clang/manifest.json` by release tag, archive URL, and SHA-256.
- Materialize upstream fixtures with `python3 scripts/sync_clang_fixtures.py`.
- External fixtures are generated into `tests/external/clang/generated/` and ignored by Git.
- Local `xcc` regression fixtures stay in `tests/external/clang/fixtures/`.

## Documentation

Project documentation is built with MkDocs and lives in `docs/`.
