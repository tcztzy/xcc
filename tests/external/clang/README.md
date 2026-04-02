# LLVM/Clang Test Fixtures

This directory keeps a manifest-driven LLVM/Clang baseline for `xcc` regression checks.
Upstream fixtures are fetched from a pinned LLVM release tarball and are not committed to Git.

## Provenance

- Upstream repository: `https://github.com/llvm/llvm-project`
- Upstream release tag: `llvmorg-22.1.0`
- Upstream archive URL: `https://api.github.com/repos/llvm/llvm-project/tarball/llvmorg-22.1.0`
- Upstream archive SHA-256: recorded in `tests/external/clang/manifest.json`
- Upstream license: Apache-2.0 WITH LLVM-exception
- Fixture inventory and checksums: `tests/external/clang/manifest.json`

## Scope

The baseline currently rewrites `manifest.json` from scratch from all pinned `clang/test/**/*.c`
fixtures. Each case is classified coarsely as either:

- `ok`: the source should compile without a frontend diagnostic, or
- `error`: the source is annotated with Clang `expected-*` diagnostics and any frontend failure is acceptable.

Fixtures that do not match the current `xcc` behavior are recorded with `skip_reason` so the full
suite stays green while features are implemented incrementally.

Fixture classes:

- **External fixtures**: upstream `clang/test/...` files materialized under `tests/external/clang/generated/`.
- **Local fixtures**: `xcc/local/...` regression files tracked under `tests/external/clang/fixtures/`.

## Update Rule

When rebuilding the full-suite baseline:

1. Download the pinned archive from scratch.
2. Rewrite `manifest.json` from the archive inventory, not from previous case rows.
3. Keep generated fixtures byte-identical to the upstream release archive.
4. Remove `skip_reason` entries only when `xcc` gains the required behavior.

## Baseline Workflow

- Rewrite the full upstream baseline from scratch and force a fresh download:
  - `python3 scripts/sync_clang_fixtures.py --rebuild-full-suite-baseline --force-download`
- Verify local fixtures and checksums against the pinned archive:
  - `python3 scripts/sync_clang_fixtures.py --check`
- Run the dedicated suite:
  - `XCC_RUN_CLANG_SUITE=1 python3 -m unittest -v tests.test_clang_suite`
