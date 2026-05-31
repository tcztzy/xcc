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
- Native codegen cannot treat inline-use discovery as direct-call-only. Inline
  functions can be required by function-pointer tables, conditional designators,
  or `extern inline` bodies even when no call expression names them directly.
- When a backend emits an inline body because it did not inline the call, emit
  it with translation-unit-local linkage. Header inline helpers commonly appear
  in many objects and must not become duplicate external definitions.
- Compiler builtins are not library calls. If the frontend accepts a
  `__builtin_*` name, each target backend needs either a real lowering or an
  early diagnostic; otherwise whole-program builds fail late at link time.
- On Darwin AArch64, imported data symbols are not ordinary page-addressable
  labels. Load their address through GOT relocations first, then load/store the
  variable value through that address.
- Direct calls and function designator addresses need different Mach-O
  relocations for external functions: `bl _name` is fine for calls, but taking
  an imported function's address must load it through the GOT.
- Function-call argument evaluation needs an ABI save plan, not just
  left-to-right emission. Any later argument or indirect callee that performs a
  nested call can overwrite x0-x7 or d0-d7 values already prepared for the
  outer call.
- Binary-expression lowering needs the same preservation discipline. A left
  operand kept only in a caller-scratch temp register can be overwritten by
  recursive RHS arithmetic or calls before the final compare/operator uses it.
- Compound assignment is a binary operation after the lvalue load. For local
  scalars, spill the old value across RHS lowering before applying `+=`,
  `*=`, shifts, or bitwise operators.
- Do not keep a local array element destination address live in x11 while
  evaluating a scalar initializer. Address calculation is cheap and
  side-effect-free; recompute it after the value is ready.
- Do not assume stack slots fit AArch64's immediate load/store operands. Large
  CPython frames can place scratch/spill slots past the direct SP-offset range;
  materialize the address in a scratch GPR first.
- Update expressions can be nested inside address formation. If the requested
  result register is also the usual lvalue-address scratch, pick a different
  address register for the load-modify-store.
- Large-offset stack helper code has its own scratch-register effects. When an
  aggregate source address is live in x12, reload saved destination addresses
  with a materialization scratch that cannot overwrite x12.
- Argument-preservation helpers must not make untracked dynamic `sp` changes
  before recursively lowering nested call arguments; local slot offsets are
  frame-relative only under the planned stack layout.
- When a call result occupying x0/x1 or d0/d1 becomes a later argument, move
  overlapping return registers high-to-low so x0→x1 does not overwrite the
  source for x1→x2.
- Pointer subscript scaling has three live roles: base, index, and scale. For
  non-power-of-two element sizes, choose a scale scratch distinct from both
  base and index before multiplying.
- In nested subscript lowering, an outer index register stays live while the
  base expression is recursively lowered. Allocate index scratch registers by
  nesting depth instead of reusing one fixed register for every level.
- Nested subscript scale materialization must also respect the live-index set;
  otherwise a non-power-of-two inner row size can overwrite the outer column
  index after the index-register allocation itself has been fixed.
- String literal prefix matters in native data emission. `L""`, `u""`, and
  `U""` are not byte cstrings; pointer initializers must reference storage
  encoded at the literal's target code-unit width.
- Real-build compiler wrappers must preserve the caller's working directory.
  For relative compile inputs, prefer a `PYTHONPATH=... python -c ...` wrapper
  over `uv --directory ... run xcc`, which changes cwd and makes
  project-relative source paths disappear.
