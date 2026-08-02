# XCC Specification

This file is the single entry point for XCC's current contract. The files under
[`specs/`](specs/) refine it by subsystem. Together they describe required
behavior; tests enforce that behavior.

Historical plans, audits, bug narratives, and completed work are not
specifications. Use Git history for old text, [`CHANGELOG.md`](CHANGELOG.md) for
capability and status, and [`LESSONS.md`](LESSONS.md) for reusable engineering
lessons.

## Project Contract

- XCC is a C11 compiler and CC-style driver written for CPython 3.11+.
- Runtime code uses only the Python standard library.
- Runtime source must not use `from __future__ import annotations`.
- GPL-derived source and tests are forbidden.
- Compiler behavior must be project-neutral. CPython paths, filenames, macros,
  or project identity must never select a special compiler path.
- A behavior change requires the smallest practical regression reproducer and,
  where useful, an independent oracle such as clang or CPython.
- Unsupported input must fail deterministically; hidden backend fallback is
  forbidden.
- Existing user changes must be preserved, and unrelated refactors must not be
  mixed into a change.

## Owned Specs

| Area | Contract |
| --- | --- |
| Shared C frontend and semantics | [`specs/compiler.md`](specs/compiler.md) |
| Driver and target selection | [`specs/driver.md`](specs/driver.md) |
| LLVM target | [`specs/target-llvm.md`](specs/target-llvm.md) |
| Darwin AArch64 target | [`specs/target-aarch64-apple-darwin.md`](specs/target-aarch64-apple-darwin.md) |
| Linux x86_64 target | [`specs/target-x86_64-linux-gnu.md`](specs/target-x86_64-linux-gnu.md) |
| EVM target | [`specs/target-evm.md`](specs/target-evm.md) |
| AOT Python and strong bootstrap | [`specs/aot-python.md`](specs/aot-python.md) |

The narrowest owning spec wins for subsystem details. This root contract wins
for project-wide constraints.

## Validation Contract

Every code handoff must run:

```text
uv run tox -e lint
uv run tox -e type
```

Behavior changes also run the focused regression suite and the broadest
practical integration gate. The release target remains a clean CPython build:

```text
CC="xcc" ./configure && make
```

LLVM IR is lowered on this development machine through
`/opt/homebrew/opt/llvm/bin/llc`; the portable driver contract remains in the
LLVM target spec.

## Editing Rules

- Specs contain only current goals, public interfaces, constraints, and
  acceptance criteria.
- Specs do not contain task lists, completed-work tables, bug timelines, commit
  diaries, benchmark runs, or numbered implementation-history ledgers.
- Put target-neutral behavior in `compiler.md`, target selection in
  `driver.md`, and target-specific ABI or output behavior in the owning target
  file.
- Update `CHANGELOG.md` when capability or status changes.
- Update `LESSONS.md` only when a result yields a reusable lesson.
