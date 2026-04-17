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
- Run LLVM/Clang reduction through the layered multi-agent workflow in `HARNESS.md`.
- Return to CPython translation-unit trials after frontend and backend coverage justify the gate.

## Harness Queue

- `clang-p0-init-compat-001`
  - layer: `P0`
  - family: `initializer-compatibility`
  - subsystem: `sema`
  - targets: current Clang failures with `Initializer type mismatch` in scalar, union, or string/record initializer analysis
  - expected_files: `src/xcc/sema/initializers.py`, `src/xcc/sema/declarations.py`, `src/xcc/sema/statements.py`, `tests/test_sema.py`, `tests/external/clang/manifest.json`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: queued summary only; worker must generalize initializer rules and add focused regression coverage

- `clang-p2-pp-import-001`
  - layer: `P2`
  - family: `objc-style-import-directive`
  - subsystem: `preprocessor`
  - targets: current Clang failures with `Unknown preprocessor directive: #import`; treat `#import` as include-once semantics without host-specific shortcuts
  - expected_files: `src/xcc/preprocessor/**`, `tests/test_preprocessor.py`, `tests/external/clang/manifest.json`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: queued summary only; keep behavior general and do not special-case fixture names

- `clang-p0-types-001`
  - layer: `P0`
  - family: `types-and-conversions`
  - subsystem: `sema`
  - targets: current Clang failures involving integer promotions, usual arithmetic conversions, or type compatibility
  - expected_files: `src/xcc/sema/**`, `tests/test_sema.py`, `tests/external/clang/manifest.json`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: core layer; unlock more expression slices

- `clang-p0-declarators-001`
  - layer: `P0`
  - family: `declarators-and-symbol-binding`
  - subsystem: `parser,sema`
  - targets: current Clang failures involving declarator parsing, storage classes, symbol definition/lookup
  - expected_files: `src/xcc/parser/**`, `src/xcc/sema/**`, `tests/test_parser.py`, `tests/test_sema.py`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: do not run concurrently with other parser/sema hotspot slices unless file ownership is clearly disjoint

- `clang-p1-expr-001`
  - layer: `P1`
  - family: `expression-semantics`
  - subsystem: `parser,sema`
  - targets: current Clang failures involving conditional, assignment, arithmetic, or lvalue/rvalue expression rules after P0 blockers shrink
  - expected_files: `src/xcc/parser/**`, `src/xcc/sema/**`, `tests/test_parser.py`, `tests/test_sema.py`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: queue only after relevant P0 blockers are no longer dominant

- `clang-p2-pp-001`
  - layer: `P2`
  - family: `macro-and-include-edges`
  - subsystem: `preprocessor`
  - targets: current Clang failures involving macro expansion, conditionals, include handling, directive edges
  - expected_files: `src/xcc/preprocessor/**`, `tests/test_preprocessor.py`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: safe parallel candidate when parser/sema slices are running

- `clang-p3-diag-001`
  - layer: `P3`
  - family: `diagnostic-alignment`
  - subsystem: `diagnostics`
  - targets: deterministic diagnostics mismatches that remain after semantic gaps are closed
  - expected_files: `src/xcc/**`, `tests/**`, `CHANGELOG.md`
  - verification: `uv run tox -e py311 && uv run tox -e lint && uv run tox -e type && uv run tox -e clang_suite`
  - status: `todo`
  - notes: reject wording-only hacks that mask semantic bugs
