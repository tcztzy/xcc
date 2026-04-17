# XCC

XCC is an alpha C11 compiler written in Python 3.11+ with no runtime dependencies.

## Current State

- Frontend: preprocessing, lexing, parsing, semantic analysis, deterministic diagnostics.
- Driver: validates with XCC before backend selection.
- Backends: native macOS `arm64` assembly for the implemented subset, strict `--backend=xcc`, fallback-capable `--backend=auto`, and explicit `--backend=clang`.
- Toolchain gap: `clang` still performs assembly and linking.
- Long-term target: compile CPython without source changes.

## Commands

- Install: `uv sync --dev`
- Test: `uv run tox -e py311`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Clang fixtures materialize: `uv run python scripts/sync_clang_fixtures.py`
- Clang fixtures check: `uv run python scripts/sync_clang_fixtures.py --check`
- Clang fixtures suite: `uv run tox -e clang_suite`
- Native smoke: `uv run tox -e native_smoke`
- Linux containers: `uv run tox -e docker_glibc` or `uv run tox -e docker_musl`
- Docs: `uv run mkdocs build --strict`

## Rules

- Standard library only at runtime.
- No GPL-derived code or tests.
- 100% line and branch coverage.
- Every behavior change needs a focused test.
- Cached specs and generated upstream fixtures stay uncommitted.
