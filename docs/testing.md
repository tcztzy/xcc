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
