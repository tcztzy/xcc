# XCC Specs

This file is the root entrypoint for project specifications. Detailed specs
live under `specs/` so each track can evolve without turning one file into a
mixed ledger.

## Spec Map

- `specs/compiler.md` → current C compiler spec, task ledger, and bug ledger.
- `specs/aot-python.md` → AOT Python subset and strong-bootstrap contract.
- `specs/driver.md` → shared target-selection/default contract.
- `specs/target-llvm.md` → LLVM target contract.
- `specs/target-aarch64-apple-darwin.md` → Darwin AArch64 target contract.
- `specs/target-x86_64-linux-gnu.md` → Linux x86_64 target contract.
- Concrete target specs use one `specs/target-<name>.md` file per target, are
  listed above individually, and must not be collapsed into `specs/targets.md`.

## Update Rules

- Update the narrowest spec that owns the change.
- Keep behavior invariants close to the subsystem they constrain.
- Put concrete target behavior in that target's own `specs/target-<name>.md`;
  do not create a shared `specs/targets.md`.
- Keep root `SPEC.md` as an index only.
- When a bug creates a reusable lesson, update `LESSONS.md`.
- When project capability/status changes, update `CHANGELOG.md`.
