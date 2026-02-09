# XCC Agent Instructions

This repository aims to become a C11 compiler written in modern Python (CPython and PyPy, 3.11+). The long-term target is to compile the CPython source tree.

## Hard Constraints

- **No GPL code**: do not copy, translate, or derive from GPL-licensed sources (including test suites). Prefer permissive licenses or official specifications.
- **No third-party runtime dependencies**: `xcc` must run using the Python standard library only. Third-party tools are allowed for development (lint/type/test/docs).
- **Python support**: must run on **CPython 3.11+** and **PyPy 3.11+**.
- **Minimum supported Python policy**: the lowest supported CPython 3.x version tracks the newest 3.x supported by PyPy. As of now, PyPy supports 3.11 but not 3.12, so the minimum is 3.11+.
- **No `from __future__ import annotations`**: do not use it in this codebase.
- **Quality gates**:
  - Lint: `ruff` (no warnings).
  - Type check: `ty` (no warnings).
  - Tests: `tox` + `unittest`.
  - Coverage: **100% line + branch coverage**. Every diagnostic path must be exercised.
- **Docs & comments**: keep them **concise and professional in English**.
- **Implementation minimality**: when behavior is equivalent, prefer implementations with fewer lines, bytes, and tokens (after formatter like `ruff`).

## Development Workflow

- Add dev dependencies via `uv add --dev <deps>` (do not hand-edit `pyproject.toml` for dependency changes).
- Run local tests: `tox -e py311` (coverage is enforced).
- Run lint/type checks: `tox -e lint` and `tox -e type`.

## Linux/ELF Testing (via tox-docker)

On macOS, Linux/ELF validation happens in Docker via tox-docker:

- Build images: `./scripts/docker-build.sh glibc` and `./scripts/docker-build.sh musl`
- Run containerized tests:
  - glibc: `tox -e docker_glibc`
  - musl: `tox -e docker_musl`

Notes:
- Linux targets assume the **mold** linker.
- libc targets include **glibc** and **musl** (tested separately).
- Do not set up or run `tox` *inside* the container; tox-docker drives the container lifecycle.

## Documentation Sources

External specs (PDF/TXT/HTML) are cached under `docs/_sources/` for convenience, but **must not be committed** (the directory is gitignored).

## Code Hygiene Checklist (before submitting changes)

- New behavior has `unittest` coverage (including error paths).
- Coverage stays at 100% (line + branch).
- `ruff` and `ty` are clean.
- No new non-stdlib runtime dependency.
- No license contamination (double-check any copied tables/grammar snippets).
