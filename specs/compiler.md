# Shared C Compiler Contract

## Goal and Scope

XCC provides a Python-standard-library-only C11 frontend, semantic model, and
CC-style compilation pipeline. This file owns behavior shared by all targets.
Target selection belongs to [`driver.md`](driver.md); ABI, assembly, relocation,
and link behavior belong to the selected target spec.

## Public Pipeline

| Surface | Owner |
| --- | --- |
| Preprocessing | `src/xcc/preprocessor/` |
| Tokenization | `src/xcc/lexer.py` |
| Parsing and AST construction | `src/xcc/parser/` |
| Types, constants, layout, and conversions | `src/xcc/sema/` |
| CC-style command | `xcc ...` |
| Regression suite | `uv run python -m unittest discover -v` |

## Required Behavior

- The frontend supports C11 plus explicitly tested GNU extensions. A driver
  `-std=<mode>` option controls preprocessing, parsing, and semantic analysis;
  accepting the flag while silently using GNU mode is forbidden.
- Preprocessing preserves C macro rescan and self-disable rules, multiline
  arguments, comments, conditional directives, include behavior, and
  deterministic source locations.
- Parsing preserves lexical scope, declaration identity, declarator structure,
  tags, attributes, statement expressions, initializers, and control flow.
- Semantic analysis applies C integer promotions and conversions, pointer and
  array decay, compatible-type rules, constant evaluation, aggregate layout,
  bit-field layout, and storage duration consistently across targets.
- Incomplete array sizes are completed from their initializer's greatest
  initialized index plus one, not from initializer item count.
- GNU `return expression;` in a `void` function evaluates the expression for
  side effects before returning; strict C11 mode rejects it.
- Diagnostics have stable messages and locations. Unsupported behavior raises a
  target-appropriate diagnostic instead of falling back to another compiler.
- Project-specific source identities must not affect compiler semantics.

## §V Invariants

- V1: Normalizing `FrontendOptions` is idempotent, preserves every supplied
  field, and never injects target- or bootstrap-specific include paths or
  macros into the shared frontend configuration.
- V2: Every compilation uses one target data layout. Predefined size macros,
  parser integer-constant evaluation, semantic `sizeof`/`_Alignof` and backend
  storage decisions must agree for the selected target.
- V3: `#pragma pack(n)` sets record packing, `#pragma pack()` resets it, and
  `push`/`pop` restores the prior setting in source order; semantic and backend
  size, alignment, and member offsets use that same packing.
- V4: Semantic analysis assigns every record type specifier its exact identity;
  backends consume that identity instead of matching anonymous records by shape.
- V5: `offsetof` is an integer constant expression; array bounds use its exact
  semantic record layout, including nested member paths.
- V6: Parsing the 19 nested parenthesized expression levels emitted by CPython
  headers does not exhaust the host call stack.
- V7: An unsized array compound literal derives its bound from its initializer;
  array decay and pointer arithmetic retain every initialized element.
- V8: `_Thread_local` objects have distinct storage in each native thread;
  definitions and external references both use thread-local storage.
- V9: An ordinary one-byte character constant uses the signed execution
  character value; constant folding and runtime conversion agree for bytes
  such as `\x80`.
- V10: Semantic analysis computes each record's physical layout once. `sizeof`,
  `_Alignof`, `offsetof`, initializers, and every native backend consume that
  same member-offset and bit-field map instead of recomputing layout rules.
- V11: Narrow string literals are encoded once in the shared semantic layer.
  Hexadecimal and octal escapes contribute their declared byte values without
  UTF-8 re-encoding; source characters and universal character names use UTF-8.
  Every backend consumes the same bytes.
- V12: A constant integer converted to a pointer or function pointer is first
  represented at the target pointer width with its C integer value preserved;
  negative sentinels such as `(callback_type)-1` must not become a
  zero-extended 32-bit address on a 64-bit target.
- V13: Floating-point inequality and scalar-to-boolean conversion use unordered
  comparison semantics, so NaN compares unequal to every value (including
  itself) and converts to true as required by C.
- V14: Every argument beyond a variadic function's declared parameters receives
  C's default argument promotions on direct and indirect calls. Integer types
  narrower than `int` promote with their source signedness, and `float`
  promotes to `double`.
- V15: Static pointer initializers preserve relocatable address arithmetic.
  Array decay followed by an integer offset emits a constant address scaled by
  the pointed-to element type; a valid address expression never falls back to
  null merely because it is not a bare symbol.

## Regression Expectations

- Parser or semantic fixes include a minimized C reproducer.
- Layout changes exercise `sizeof`, `_Alignof`, `offsetof`, member order, and
  relevant bit-field or flexible-array cases.
- Conversion changes exercise signedness, width, constant folding, and runtime
  behavior where practical.
- Initializer changes exercise scalar, nested aggregate, local, static, and
  file-scope forms as applicable.
- Control-flow changes exercise side effects and all affected exits.
- clang is the preferred oracle for valid C behavior when the behavior is not
  target-specific.

## Acceptance

Focused tests must pass, followed by `uv run tox -e lint` and
`uv run tox -e type`. High-risk frontend or semantic changes also run a real,
clean build gate; stale object files must not be allowed to mask a regression.
