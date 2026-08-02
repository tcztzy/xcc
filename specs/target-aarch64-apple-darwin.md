# Darwin AArch64 Target Contract

## Goal and Output

`--target=aarch64-apple-darwin` emits native Mach-O AArch64 assembly through
`src/xcc/aarch64_asm.py`. `-c` assembles that text and link actions use the
Darwin toolchain. LLVM IR and `llc` are forbidden on this target path.

The integration gate is:

```text
CC="xcc --target=aarch64-apple-darwin" ./configure && make
```

The resulting CPython executable must start and pass a smoke import on the
development machine.

## ABI and Data Model

- Scalar integer, pointer, float, and double values follow the Darwin AArch64
  ABI, including register classes, stack overflow arguments, return values, and
  stack alignment.
- Small integer aggregates, homogeneous floating aggregates, unions, large
  indirect returns through `x8`, and by-value aggregate arguments follow the
  platform ABI without scalarizing aggregate storage.
- Variadic calls and definitions use Darwin's stack-based unnamed argument
  model and valid `va_list` operations.
- Record, union, enum, array, flexible-array, bit-field, atomic, wide-character,
  and `long double` size and alignment agree with semantic layout and target
  conventions.
- Large frames and offsets are materialized through registers when instruction
  immediates cannot encode them.

## Language Semantics

- Native lowering supports ordinary C lvalues, pointer arithmetic, casts,
  calls and function pointers, nested scopes, declarations, all structured
  loops, switch, labels/goto, conditional and comma expressions, and
  short-circuit behavior.
- Aggregate assignment, compound literals, record returns, array decay, and
  local/static/global initializers preserve C value, storage, zero-fill,
  designator, and relocation semantics.
- Bit-field reads, writes, updates, and initialization change only the selected
  storage bits.
- Used inline functions and supported compiler/atomic builtins lower to native
  code; unused inline bodies do not block compilation and unresolved synthetic
  builtin symbols are forbidden.

## Mach-O Rules

- Local and external functions, data, cstrings, literal pools, static locals,
  compound literals, and subobject addresses use valid Mach-O symbols,
  sections, relocations, and addends.
- External data and function addresses use the platform's indirect access rules
  where direct page relocations are invalid.
- File-scope declarations emit storage exactly when C linkage and definition
  rules require it.

## Acceptance

Prefer executable source tests for semantics and focused assembly assertions for
target-only ABI or relocation behavior. High-risk changes run assembly,
link/execution, and the clean CPython integration gate without CPython-specific
compiler branches.
