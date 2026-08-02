# Current Specifications

This directory contains only XCC's current, normative subsystem contracts.
Start at [`../SPEC.md`](../SPEC.md) for project-wide rules and the ownership
map.

## Structure

- `compiler.md`: shared C frontend, semantics, and validation.
- `driver.md`: target selection and CC-style actions.
- `target-*.md`: one contract per concrete output target.
- `aot-python.md`: the Python subset compiler and strong-bootstrap proof.

## What Belongs Here

Keep stable requirements, supported interfaces, forbidden behavior, and
acceptance gates. Prefer thematic bullets and small tables over numbered
micro-invariants.

Do not add task or bug ledgers. Record current status in `CHANGELOG.md`,
reusable lessons in `LESSONS.md`, and temporary implementation plans under
`docs/`. Historical documents are context, not a second source of truth.
