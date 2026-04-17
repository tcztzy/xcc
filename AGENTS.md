# XCC Agent Instructions

- Runtime code uses only the Python standard library.
- Support CPython and PyPy 3.11+.
- Do not use `from __future__ import annotations`.
- Do not copy or derive from GPL sources or tests.
- Add tests before behavior changes.
- Keep coverage at 100% line and branch.
- Run `uv run tox -e py311`, `uv run tox -e lint`, and `uv run tox -e type` before handoff.
- Keep `TODO.md` for current planning, `CHANGELOG.md` for current status, and `LESSONS.md` for concise project lessons.
- Generated LLVM/Clang fixtures live under `tests/external/clang/generated/` and stay uncommitted.
