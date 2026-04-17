# XCC Multi-Agent Harness

## Goal

Drive `tests/external/clang` toward full pass coverage with parallel Codex workers while keeping the tree reviewable and the fixes general.

## Roles

- **Supervisor**: triage current LLVM/Clang failures, pick ready slices, assign workers, review results, enforce quality gates.
- **Worker**: own exactly one claimed slice, make the smallest general fix, verify, commit, stop.
- **Quality reviewer**: independently reject hard-coded or test-specific hacks before a slice is accepted.

## Dependency layers

Workers may run in parallel only within the same ready layer.

- **P0 core semantics**: declarators, types, conversions, constant evaluation, symbol/sema invariants
- **P1 expression and statement semantics**: operators, control flow, lvalues/rvalues, statement lowering assumptions
- **P2 frontend surface area**: preprocessor edges, initializers, attributes, declarations syntax corners
- **P3 diagnostics and compatibility tails**: wording/alignment issues, unsupported-tail cleanup, fixture metadata follow-ups

Do not dispatch a higher layer while lower-layer blockers still explain the same family of failures.

## Slice design

A good slice is a bucket of tests with all three properties:

1. same dependency layer
2. same failure family
3. same primary subsystem

Examples:

- `P0 + integer conversions + sema`
- `P1 + conditional operator + parser/sema`
- `P2 + macro expansion edge cases + preprocessor`

Avoid mixing unrelated families just to fill a worker.

## Parallelism rules

- Default: at most **3 workers per round**.
- Use fewer if slices touch the same hotspot files.
- Never run two workers concurrently if both are expected to edit the same hotspot area in `src/xcc/parser`, `src/xcc/sema`, or `src/xcc/preprocessor`.
- Prefer disjoint file ownership or clearly separated helper modules.
- Each worker gets one branch, one worktree, one slice, one commit.

## Acceptance rules

A worker result is acceptable only if all are true:

1. touched files match the claimed slice
2. tests added or updated for the new behavior
3. `uv run tox -e py311` passes
4. `uv run tox -e lint` passes
5. `uv run tox -e type` passes
6. relevant clang-suite slice passes or the targeted failures are reduced
7. tree is clean after commit

## Quality control

Reject any slice that does any of the following:

- hard-codes fixture names, source file names, timestamps, host paths, or compile times
- special-cases a single LLVM/Clang test without a language-level reason
- adds fake values just to satisfy expected output
- inflates skip lists instead of fixing behavior
- gates behavior on fixture-specific strings or comments
- weakens diagnostics/tests merely to get green

Required standard:

- explain the underlying language rule or compiler invariant being implemented
- prefer general parser/sema/preprocessor logic over test-name branching
- add a reproducer first when changing behavior
- keep diagnostics deterministic
- preserve portability and avoid host-specific assumptions

## Review protocol

For every worker slice, the supervisor must run an independent review pass that answers:

1. what general rule changed?
2. why is this not fixture-specific?
3. what prevents the same fix from regressing neighboring tests?
4. did the change introduce any hard-coded behavior or suspicious constants?

If these answers are weak, reject or send repair work.

## Queue format

Keep the human-readable queue summary in `TODO.md` using this shape. Live claim/status state is stored in `.worktrees/harness/tasks.json` and managed via `scripts/harness_queue.py`:

- `id`
- `layer`
- `family`
- `subsystem`
- `targets`
- `expected_files`
- `verification`
- `status: todo|claimed|review|done|blocked` as the default/manual status in `TODO.md`; active claim state comes from the JSON state file
- `notes`

## Supervisor cleanliness policy

Supervisor root (`~/GitHub/xcc`) is allowed to carry orchestration-only metadata edits in:

- `HARNESS.md`
- `CHANGELOG.md`

Do not let queue claims dirty `TODO.md`; claim/status churn must stay in `.worktrees/harness/tasks.json`, which is ignored by Git.

Do not launch workers if the supervisor root has uncommitted implementation changes in compiler or test code such as:

- `src/xcc/**`
- `tests/**` except queue/changelog-style metadata updates
- scripts or tooling that would conflict with worker output

Worker worktrees must always start clean, end clean after commit, and stay isolated to their claimed slice.

## Supervisor loop

1. read `AGENTS.md`, `LESSONS.md`, `TODO.md`, `HARNESS.md`, `CHANGELOG.md`
2. inspect supervisor-root dirtiness and continue only if any uncommitted changes are orchestration-only metadata edits; block on implementation-code dirtiness
3. inspect current clang-suite failures/skips
4. group candidate tests by `layer + family + subsystem`
5. choose up to 3 non-conflicting ready slices
6. dispatch one fresh Codex worker per slice in a clean isolated worktree/branch
7. independently review each result for quality and anti-hardcoding
8. accept, reject, or emit repair slices
9. report remaining frontier and next core layer blockers

For cron-safe selection without launching workers, use `python3 scripts/harness_supervisor.py`. It blocks on a dirty supervisor root, verifies claimed/review task state against live worktrees, reports clean orphan worktrees, and emits a stable JSON summary. Add `--claim` only when the caller wants the selected task claimed in `.worktrees/harness/tasks.json`.
