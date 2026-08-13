# XCC Agent Instructions

- Do not create, switch to, or use additional Git branches. Work directly on the checked-out mainline branch (`master` in this repository).
- Runtime code uses only the Python standard library.
- Support CPython 3.11+.
- No `from __future__ import annotations`.
- No GPL sources or tests.
- Run `uv run tox -e lint` and `uv run tox -e type` before handoff.
- Keep `CHANGELOG.md` for status, `LESSONS.md` for lessons.
- LLVM IR output goes through `/opt/homebrew/opt/llvm/bin/llc`.
- Target: `CC="xcc" ./configure && make` in CPython succeeds without CPython-specific compiler paths.
