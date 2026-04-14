# Testing

## Test framework

- Use the standard library `unittest` module for all tests.
- Tests must be deterministic and hermetic.

## Coverage requirements

- Enforce 100% line coverage and 100% branch coverage.
- The "over 100%" requirement is interpreted as full line and branch coverage plus additional negative and stress tests that exercise error paths.

## Test layers

- Unit tests for lexer, parser, semantic analysis, driver behavior, and native backend rejection paths.
- Golden tests for diagnostics and error messages.
- Native backend smoke tests for macOS `arm64`.
- Regression tests for reported bugs.
- Curated upstream LLVM/Clang fixture tests for cross-checking accepted and rejected C inputs.

## Curated LLVM/Clang fixtures

- Upstream fixtures are materialized under `tests/external/clang/generated/` from a pinned LLVM release archive.
- Local `xcc` regression fixtures are tracked under `tests/external/clang/fixtures/`.
- Metadata, upstream archive pin, and checksums are stored in `tests/external/clang/manifest.json`.
- The harness in `tests/test_clang_suite.py` validates fixture integrity, coarse expectations (`ok` / `error`), and selected frontend-stage or diagnostic-location details where the manifest records them.
- Direct `unittest` runs require `XCC_RUN_CLANG_SUITE=1`: `XCC_RUN_CLANG_SUITE=1 python3 -m unittest -v tests.test_clang_suite`.
- Or use tox: `tox -e clang_suite`.
- Materialize external fixtures from upstream with `python3 scripts/sync_clang_fixtures.py`.

## Tooling

- Use `tox` to run tests across supported interpreters and configurations.
- Use `coverage` to gate line and branch coverage thresholds.
  - Coverage is enforced at 100% for line and branch coverage.

Common commands:

- `tox -e py311`
- `tox -e lint`
- `tox -e type`
- `tox -e clang_suite`
- `tox -e native_smoke`

## Docker (Linux/ELF)

Linux/ELF testing runs inside Docker containers. The images are intentionally minimal and do not install tox, so use direct `python3 -m unittest` commands.

Example:

- `./scripts/docker-run.sh glibc python3 -m unittest discover -v`

## Optional tox-docker

Tox manages Linux containers via tox-docker for glibc/musl test runs. The tests are executed inside the running containers using `docker exec`.

Examples:

- `tox -e docker_glibc`
- `tox -e docker_musl`

## References

- Python `unittest` documentation.
- `tox` documentation.
- `coverage` documentation (branch coverage and configuration).
