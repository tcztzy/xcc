# Curated LLVM/Clang Test Fixtures

This directory vendors a small, pinned subset of upstream LLVM/Clang tests for `xcc` regression checks.

## Provenance

- Upstream repository: `https://github.com/llvm/llvm-project`
- Upstream snapshot commit: `9898082bd358e1706f7703291bdec6caae12993a`
- Upstream license: Apache-2.0 WITH LLVM-exception
- Fixture inventory and checksums: `tests/external/clang/manifest.json`

## Scope

The curated subset is intentionally small and currently checks only whether `xcc`:

- accepts selected valid Clang parser fixtures, or
- rejects selected invalid fixtures at the expected diagnostic stage (`lex`, `parse`, or `sema`).
- emits expected diagnostic text and source coordinates for selected negative cases.

The harness does not run Clang `lit`/`FileCheck` directives yet.

## Update Rule

When adding or replacing fixtures:

1. Keep files byte-identical to upstream.
2. Update `manifest.json` with upstream path, expected stage, and SHA-256 checksum.
3. Prefer manifest-driven assertions (`message_contains`, `line`, `column`) over test-code special cases.

## Syncing fixtures

- Refresh fixtures and checksums from the pinned commit:
  - `python scripts/sync_clang_fixtures.py`
- Verify local fixtures against upstream without writing:
  - `python scripts/sync_clang_fixtures.py --check`
- Sync from a different commit:
  - `python scripts/sync_clang_fixtures.py --commit <llvm-commit>`
