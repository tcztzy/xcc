# XCC Specification

This file is the single entry point for XCC's current contract. The files under
[`specs/`](specs/) refine it by subsystem. Together they describe required
behavior; tests enforce that behavior.

Historical plans, audits, bug narratives, and completed work are not
specifications. Use Git history for old text, [`CHANGELOG.md`](CHANGELOG.md) for
capability and status, and [`LESSONS.md`](LESSONS.md) for reusable engineering
lessons.

## §G GOAL

XCC is a C11 compiler and CC-style driver, written for CPython 3.11+, whose
release target is a successful clean CPython build with `CC="xcc"`.

## §C CONSTRAINTS

- C1: Runtime code uses only the Python standard library.
- C2: Runtime source must not use `from __future__ import annotations`.
- C3: GPL-derived source and tests are forbidden.
- C4: Existing user changes must be preserved, and unrelated refactors must not
  be mixed into a change.
- C5: LLVM IR is lowered on this development machine through
  `/opt/homebrew/opt/llvm/bin/llc`; the portable driver contract remains in the
  LLVM target spec.
- C6: Specs contain only current goals, public interfaces, constraints, and
  acceptance criteria.
- C7: Specs do not contain task lists, completed-work tables, bug timelines,
  commit diaries, benchmark runs, or numbered implementation-history ledgers.
- C8: Capability and status changes go in `CHANGELOG.md`; reusable engineering
  lessons go in `LESSONS.md`; historical reasoning remains in Git history.

## §I INTERFACES

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

## §V INVARIANTS

- V1: Compiler behavior must be project-neutral. CPython paths, filenames,
  macros, or project identity must never select a special compiler path.
- V2: A behavior change requires the smallest practical regression reproducer
  and, where useful, an independent oracle such as clang or CPython.
- V3: Unsupported input must fail deterministically; hidden backend fallback is
  forbidden.
- V4: Put target-neutral behavior in `specs/compiler.md`, target selection in
  `specs/driver.md`, and target-specific ABI or output behavior in the owning
  target file.
- V5: Every code handoff must pass the lint and type validation commands below.
- V6: Behavior changes must pass the focused regression suite and the broadest
  practical integration gate.
- V7: The release target remains a clean CPython build using the public compiler
  path, without CPython-specific compiler dispatch.
- V8: Push validation watches the repository's actual default branch. Required
  tool-dependent integration checks use the documented portable resolver or
  fail explicitly instead of silently skipping an installed tool.

### Validation Contract

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
`/opt/homebrew/opt/llvm/bin/llc` as required by §C.5.
