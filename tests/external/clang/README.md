# Curated LLVM/Clang Test Fixtures

This directory keeps a manifest-driven subset of LLVM/Clang tests for `xcc` regression checks.
Upstream fixtures are fetched from a pinned LLVM release tarball and are not committed to Git.

## Provenance

- Upstream repository: `https://github.com/llvm/llvm-project`
- Upstream release tag: `llvmorg-22.1.0`
- Upstream archive URL: `https://api.github.com/repos/llvm/llvm-project/tarball/llvmorg-22.1.0`
- Upstream archive SHA-256: recorded in `tests/external/clang/manifest.json`
- Upstream license: Apache-2.0 WITH LLVM-exception
- Fixture inventory and checksums: `tests/external/clang/manifest.json`

## Scope

The curated subset is intentionally small and currently checks only whether `xcc`:

- accepts selected valid Clang parser fixtures, or
- rejects selected invalid fixtures at the expected diagnostic stage (`lex`, `parse`, or `sema`).
- emits expected diagnostic text and source coordinates for selected negative cases.

The harness does not run Clang `lit`/`FileCheck` directives yet.

Fixture classes:

- **External fixtures**: upstream `clang/test/...` files materialized under `tests/external/clang/generated/`.
- **Local fixtures**: `xcc/local/...` regression files tracked under `tests/external/clang/fixtures/`.

## Update Rule

When adding or replacing fixtures:

1. Keep external files byte-identical to upstream release archives.
2. Update `manifest.json` with upstream path, expected stage, and SHA-256 checksum.
3. Prefer manifest-driven assertions (`message_contains`, `line`, `column`) over test-code special cases.

## Syncing fixtures

- Materialize external fixtures from the pinned release archive:
  - `python scripts/sync_clang_fixtures.py`
- Verify local fixtures and checksums against the pinned archive:
  - `python scripts/sync_clang_fixtures.py --check`
- Recompute external-case checksums in the manifest (only for intentional upstream upgrades):
  - `python scripts/sync_clang_fixtures.py --update-sha`
