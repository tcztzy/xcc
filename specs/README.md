# Specs

Project specifications are split by ownership boundary instead of living in one
large root file.

## Files

- `compiler.md` keeps shared C frontend, semantic, and compiler-wide
  constraints only.
- `driver.md` owns shared target-selection/default rules.
- `target-llvm.md` owns the LLVM target.
- `target-aarch64-apple-darwin.md` owns the Darwin AArch64 target.
- `target-x86_64-linux-gnu.md` owns the Linux x86_64 target.

## Conventions

- Use `§G`, `§C`, `§I`, `§V`, `§T`, and `§B` sections when a spec needs the
  full goal/constraint/interface/invariant/task/bug shape.
- Add or update one `target-<name>.md` per concrete target.
- Reserve `target-<name>.md` filenames for concrete targets only.
- Do not create `targets.md`; concrete targets each get their own
  `target-<name>.md`.
- Keep shared target-selection/default rules in `driver.md`.
- Keep concrete target behavior out of `compiler.md`; each target owns its own
  `target-<name>.md`.
- Keep status changes in `CHANGELOG.md`.
- Keep reusable bug lessons in `LESSONS.md`.
- Avoid duplicating long invariant lists across specs; reference the owning
  spec instead.
