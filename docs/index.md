# XCC

XCC is an alpha C11 compiler in Python 3.11+ with no runtime dependencies.

## Current State

- Frontend validation covers preprocessing, lexing, parsing, semantic analysis, and deterministic diagnostics.
- Driver mode validates with XCC before native or `clang` backend selection.
- Native backend emits macOS `arm64` assembly for the implemented subset.
- Assembly, linking, full native object emission, Linux/ELF, and CPython builds remain open.

## Gates

- `uv run tox -e py311`
- `uv run tox -e lint`
- `uv run tox -e type`
- `uv run python scripts/sync_clang_fixtures.py`
- `uv run python scripts/sync_clang_fixtures.py --check`
- `uv run tox -e clang_suite`
- `uv run mkdocs build --strict`
