# XCC Multi-Agent Harness

This file defines how `xcc` should be adapted for multi-agent development and how future agents should cooperate once the harness is in place.

## Goal

Increase safe agent concurrency by:
- reducing conflict hotspots through modularization
- publishing explicit task slices
- letting subagents claim slices from a shared queue
- keeping a supervisor responsible for validation, conflict handling, and merge order

## Core Model

1. Modularize hotspots first.
2. Publish small, explicit slices.
3. Let worker agents claim slices in isolated worktrees.
4. Require green gates and a clean tree for every accepted slice.
5. If slices conflict or a worker fails, the supervisor resolves it directly or inserts a higher-priority Codex repair task.

## Hard Rules

- Never edit upstream LLVM/Clang tests.
- Every implementation slice must run in an isolated git worktree/branch.
- One conflict domain may have only one active writer slice at a time.
- Every accepted slice must be a single reviewable commit.
- Required acceptance gates for code/tooling slices:
  - `tox -e py311`
  - `tox -e lint`
  - `tox -e type`
- Every accepted slice must leave the working tree clean.

## Conflict Domains

At minimum, track these independent write domains:
- `parser`
- `sema`
- `preprocessor`
- `lexer`
- `backend-driver`
- `fixtures-manifest`
- `docs-meta`

A worker may not claim a slice in a domain that already has an active writer.

## Supervisor Responsibilities

The supervisor is the orchestrator, not the default implementer.

The supervisor must:
- read `AGENTS.md`, `LESSONS.md`, `TODO.md`, and this file before choosing work
- keep the main repository clean before starting any new slice
- publish and prioritize slices
- assign or let workers claim slices
- review results and enforce gates
- detect scope creep, forbidden file edits, or domain conflicts
- decide merge order
- when needed, create a higher-priority Codex repair slice instead of editing directly

## Worker Responsibilities

A worker agent must:
- claim exactly one slice
- stay within the declared conflict domain and expected file set
- avoid speculative feature work
- add or tighten reproducer coverage first when needed
- implement the minimal fix or refactor
- run required verification commands
- commit a single reviewable slice
- leave its worktree clean

## Task Queue

Use a queue section in `TODO.md` to publish slices for workers to claim.

Each slice should include at least:
- `id`
- `category`
- `domain`
- `targets`
- `expected_files`
- `verification`
- `priority`
- `dependencies`
- `status`
- `notes`

Recommended statuses:
- `todo`
- `claimed`
- `blocked`
- `review`
- `done`

## Supervisor <-> Worker Message Protocol

The supervisor and workers should communicate with a small, explicit message protocol recorded in markdown-friendly blocks. The goal is to keep handoff, claim, completion, and review deterministic without introducing heavy infrastructure.

### Required message types

- `TASK_ANNOUNCE`: supervisor publishes an available slice
- `TASK_CLAIM`: worker claims one slice
- `TASK_START`: worker confirms worktree/branch and begins execution
- `TASK_RESULT`: worker reports completion attempt
- `TASK_REVIEW`: supervisor records the review result
- `TASK_REPAIR`: supervisor publishes a higher-priority follow-up or conflict-resolution slice
- `TASK_CLOSE`: supervisor marks the slice resolved

### Canonical fields

Every message should contain these fields when relevant:
- `type`
- `task_id`
- `domain`
- `branch`
- `worktree`
- `commit`
- `status`
- `verification`
- `touched_files`
- `summary`
- `next_action`

### Markdown template

Use fenced code blocks in markdown so humans and agents can both read them.

```text
[TASK_RESULT]
task_id: parser-diagnostics-001
domain: parser
branch: agent/parser-diagnostics-001
worktree: /tmp/xcc-parser-diagnostics-001
commit: abcdef12
status: review
verification:
  - tox -e py311
  - tox -e lint
  - tox -e type
touched_files:
  - src/xcc/parser.py
  - tests/test_parser.py
summary: Tightened parser diagnostic wording for declarator-identifier rejection.
next_action: supervisor_review
```

### Minimal pseudo code

```text
supervisor_loop:
  read AGENTS.md, LESSONS.md, TODO.md, HARNESS.md
  ensure main worktree is clean
  publish next available slices into TODO.md queue section
  wait for worker result or review pending slice
  if worker result arrives:
    validate claim/domain/worktree/commit
    run gate checks
    if accepted:
      mark task done
      unlock dependent tasks
      publish next slice(s)
    elif conflict or regression:
      publish TASK_REPAIR slice at higher priority
    else:
      mark task blocked or return for fixes

worker_loop(task_id):
  read AGENTS.md, LESSONS.md, TODO.md, HARNESS.md
  emit TASK_CLAIM
  create isolated worktree/branch
  emit TASK_START
  implement only the claimed slice
  run required verification
  commit one reviewable slice
  emit TASK_RESULT
  stop and wait for supervisor decision
```

### Review rule

Workers do not self-advance to the next task. After `TASK_RESULT`, the worker stops. The supervisor decides whether to:
- accept and close the slice
- request fixes
- publish a repair/conflict slice
- unlock and announce new slices

## Worktree Workflow

Every worker slice should use a dedicated worktree.

Recommended flow:
1. Create a branch and worktree from a slice ID.
2. Run the worker only inside that worktree.
3. Verify and commit there.
4. Review the slice.
5. Merge or cherry-pick only after acceptance.
6. Remove the worktree after completion.

## Readiness Before High Concurrency

Before aggressively increasing concurrency, land these readiness slices:

### 1. Coordination infrastructure
- Add a protocol document for multi-agent rules.
- Define the supervisor/worker message protocol in `HARNESS.md`.
- Represent the claimable queue in `TODO.md`.
- Add a worktree bootstrap helper.
- Add a gate checker for slice acceptance.

### 2. Reduce code hotspot contention
- Soft-modularize `src/xcc/parser.py` into stable internal regions.
- Extract at least one low-risk parser helper submodule.
- Continue the same pattern later for `preprocessor.py` and `sema.py` when boundaries are stable.

### 3. Resume normal skipped-test reduction under the harness
- After the harness is usable, the recurring supervisor loop should consume the queue instead of choosing freeform slices.
- Prefer small LLVM/Clang skip-reduction slices whose domains are currently free.

## Immediate Refactoring Direction

To support larger agent concurrency, prioritize modularization by stable semantic boundaries rather than raw file size.

High-value early targets:
- parser diagnostics helpers
- parser extension-skipping helpers
- parser declarator-specific logic
- preprocessor macro/include/pragma helper clusters

## Acceptance Criteria For The Harness

The harness is considered ready enough for larger concurrency when:
- `HARNESS.md` is specific enough for a fresh agent to follow
- a queue file exists with explicit slice metadata
- a worktree helper exists
- a gate helper exists
- at least one hotspot file has been reorganized to reduce conflict pressure
- the normal skipped-LLVM-test supervisor loop respects this harness before resuming ordinary feature slices
