# Lessons for `xcc`

This file records practical lessons learned from public critiques of the Anthropic "Claude C Compiler" project and similar compiler efforts.

## Lessons to Apply

1. **Do not hard-code environment-sensitive values.**
   - Avoid fixed compile dates, host paths, platform assumptions, or toolchain-dependent constants.
   - Prefer explicit configuration and deterministic defaults.

2. **Treat negative tests as first-class citizens.**
   - Add invalid-code tests for every diagnostic path.
   - Keep positive and negative coverage balanced; negative cases often catch real regressions earlier.

3. **Use differential testing early and continuously.**
   - Compare parser/diagnostic/codegen behavior with trusted compilers (for example, Clang/GCC where legally usable).
   - Keep reduced reproducer seeds for every mismatch.

4. **Adopt fuzzing for semantic bugs.**
   - Generate random-but-valid C programs and compare outcomes against reference compilers.
   - Minimize and preserve failing seeds as regression tests.

5. **Test ABI/layout details explicitly.**
   - Add targeted tests for alignment, packing, calling convention boundaries, and cross-translation-unit behavior.
   - Assume ABI bugs are high severity because they can cause silent corruption.

6. **Separate CI gates by goal.**
   - Distinguish parse/diagnose correctness, code generation correctness, runtime correctness, and optimization quality.
   - A "build succeeds" signal is never enough.

7. **Run curated Clang/LLVM tests where practical.**
   - Start from a small, tracked subset that matches current `xcc` scope.
   - Respect license boundaries: LLVM/Clang tests are permissive; avoid GPL-only test sources.

8. **Prevent regressions with strict change discipline.**
   - Require a reproducer test for every bug fix.
   - Do not merge feature work that reduces diagnostic quality or test clarity.

9. **Keep support claims explicit and conservative.**
   - Document supported C11 subset, unsupported features, and known limitations.
   - Under-promise and verify before expanding claims.

10. **Prefer deterministic diagnostics and outputs.**
    - Make errors stable and machine-checkable when possible.
    - Stable output improves automated testing and debugging speed.

## Maintenance Rule

When a notable bug class appears (or an external compiler postmortem reveals a useful failure mode), add a concise lesson and at least one concrete `xcc` action item here.
