# Lessons

- Keep diagnostics deterministic and covered by negative tests.
- Do not hard-code host paths, dates, or toolchain assumptions.
- Compare against permissively licensed Clang fixtures.
- Treat ABI/layout bugs as high severity.
- Add a reproducer before changing behavior.
- Parallelize long frontend trial sweeps per translation unit, but keep reports ordered.
- When a build threatens memory, split frontend, IR generation, and `llc`
  under RSS monitoring before running `make`.
- Keep codegen's type canonicalization in lockstep with sema; a single
  `bool` vs `_Bool` mismatch can make anonymous record matching fall back to
  the default scalar size.
- Constant initializer evaluation must search function-local static globals
  before file-scope symbols, because nested CPython slot arrays refer to
  earlier local static arrays by identifier.
- Do not infer incomplete array length from initializer item count; sparse
  designators and ranges make the bound the largest initialized index plus one.
- Multi-line macro collection must operate on preprocessing structure, not just
  apparent physical lines; block comments and inactive conditional branches can
  appear inside macro arguments.
