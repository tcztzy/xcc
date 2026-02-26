# Testing

## Test framework

- Use the standard library `unittest` module for all tests.
- Tests must be deterministic and hermetic.

## Coverage requirements

- Enforce 100% line coverage and 100% branch coverage.
- The "over 100%" requirement is interpreted as full line and branch coverage plus additional negative and stress tests that exercise error paths.

## Test layers

- Unit tests for lexer, parser, semantic analysis, and IR passes.
- Golden tests for diagnostics and error messages.
- End to end tests that compile CPython components and compare outputs.
- Regression tests for reported bugs.
- Curated upstream LLVM/Clang fixture tests for cross-checking accepted and rejected C inputs.

## Curated LLVM/Clang fixtures

- Fixtures are vendored under `tests/external/clang/fixtures/`.
- Metadata, upstream commit pin, and checksums are stored in `tests/external/clang/manifest.json`.
- The harness in `tests/test_clang_suite.py` validates fixture integrity, expected frontend stage (`ok`, `lex`, `parse`, `sema`), and selected diagnostic details.
- Run only this subset with `python -m unittest -v tests.test_clang_suite`.
- Or use tox: `tox -e clang_suite`.
- Sync fixtures from upstream with `python scripts/sync_clang_fixtures.py`.

## Tooling

- Use `tox` to run tests across supported interpreters and configurations.
- Use `coverage` to gate line and branch coverage thresholds.
  - Coverage is enforced at 100% for line and branch coverage.

## Docker (Linux/ELF)

Linux/ELF testing runs inside Docker containers. The images are intentionally minimal and do not install tox, so use direct `python -m unittest` commands.

Example:

- `./scripts/docker-run.sh glibc python -m unittest discover -v`

## Optional tox-docker

Tox manages Linux containers via tox-docker for glibc/musl test runs. The tests are executed inside the running containers using `docker exec`.

Examples:

- `tox -e docker_glibc`
- `tox -e docker_musl`

## References

- Python `unittest` documentation.
- `tox` documentation.
- `coverage` documentation (branch coverage and configuration).
