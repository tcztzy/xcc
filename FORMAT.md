# CaveKit Format — XCC Profile

This repository uses the CaveKit v4 workflow with an XCC-specific storage
profile. This file is authoritative when a CaveKit skill conflicts with the
generic upstream format.

## Project Profile

- `SPEC.md` is the single entry point, while `specs/` owns subsystem details.
- Preserve the existing specification hierarchy. The narrowest owning spec wins;
  the root contract wins for project-wide constraints.
- `SPEC.md` contains only current goals, constraints, interfaces, and invariants.
- Do not add `§R`, `§T`, or `§B` ledgers to `SPEC.md`.
- External research becomes a sourced current constraint or invariant only when
  it remains part of the contract; otherwise report it without persisting it.
- The current user request is the build task. Do not add or flip task-status rows.
- Record capability and status changes in `CHANGELOG.md`.
- Turn a recurring failure into a regression test and a current `§V` invariant in
  the narrowest owning spec. Add to `LESSONS.md` only when the result is reusable.
- Git history is the bug and completed-work history. Do not create a bug ledger.
- Do not create branches. Do not commit automatically; commit only when the user
  explicitly requests it.
- Use the single main Codex agent. Do not spawn sub-agents or parallel workers.
- Preserve user changes and keep unrelated refactors out of the diff.

## Addressable Sections

Sections use fixed order and stable addresses:

```text
§G  goal: one unambiguous statement of what XCC must achieve
§C  constraints: non-negotiable implementation and workflow boundaries
§I  interfaces: root contract plus links to subsystem-owned specifications
§V  invariants: numbered, testable behavior and validation requirements
```

Reference an item as `§<section>.<number>`, for example `§V.3`. Subsystem specs
may define additional numbered invariants; cite the file and identifier together
when the root address alone would be ambiguous.

## CaveKit Loop

1. `spec` creates or amends only the named current-contract section.
2. `build` plans and implements the current user request against applicable
   `§I` and `§V` entries, naming the exact verification command for each.
3. `check` performs a read-only code-versus-spec drift report.
4. On failure, `backprop` asks whether the failure reveals a reusable invariant.
   If so, add the invariant and its regression test with the fix.

Optional `grill`, `research`, `review`, and `deepen` passes remain right-sized to
uncertainty and blast radius. They propose contract changes; `spec` is the only
general specification mutator.

## Encoding

Use compact language for specification writes without losing facts. Preserve
code, paths, identifiers, URLs, versions, error strings, SQL, regex, and quoted
text verbatim.

```text
→  leads to / becomes / triggers
∴  therefore
∀  every
∃  some
!  must
?  unknown / optional
⊥  forbidden / impossible
≠  differs from
∈  in
∉  not in
≤  at most
≥  at least
&  and
|  or
```

Compression is optional when normal prose is clearer. It must never remove a
constraint, condition, or exception.

## Validation

Every handoff runs:

```text
uv run tox -e lint
uv run tox -e type
```

Behavior changes also run the focused regression and the broadest practical
integration gate. A check is complete only when commands exit successfully and
the reported evidence names the relevant `§V` invariant.
