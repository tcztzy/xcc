# LLVM/Clang Fixtures

- Metadata and checksums: `manifest.json`.
- Generated upstream files: `generated/` (ignored).
- Local regression files: `fixtures/`.
- Upstream license: Apache-2.0 WITH LLVM-exception.

Commands:

- Materialize: `uv run python scripts/sync_clang_fixtures.py`
- Check: `uv run python scripts/sync_clang_fixtures.py --check`
- Rebuild baseline: `uv run python scripts/sync_clang_fixtures.py --rebuild-full-suite-baseline --force-download`
- Run suite: `uv run tox -e clang_suite`
