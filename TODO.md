# TODO

Current work only.

## Gates

- [x] `uv run tox -e py311`
- [x] `uv run tox -e lint`
- [x] `uv run tox -e type`
- [x] `uv run python scripts/sync_clang_fixtures.py --check`
- [x] `uv run tox -e clang_suite`
- [x] `uv run mkdocs build --strict`

## Priorities

- Reduce the curated Clang-suite skip set with tested slices.
- Expand native macOS `arm64` backend coverage.
- Keep parser, preprocessor, and sema packages small enough for parallel work.
- Return to CPython translation-unit trials after frontend and backend coverage justify the gate.
