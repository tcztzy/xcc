# CPython Compatibility

## Scope

Compiling the CPython source tree is a long-term compatibility target for XCC. The compiler must eventually be compatible with CPython's supported C standard and build requirements, but CPython compilation is not part of the current day-to-day acceptance gate.

## Current status

- Current acceptance is driven by unit tests, curated LLVM/Clang fixtures, and backend smoke checks.
- The repository does not maintain a standing CPython trial script or pinned CPython source-archive gate.
- CPython validation should return only when the frontend and backend have enough coverage to justify the maintenance cost.

## Build system interaction

- The compiler must work with CPython's existing build system and flags.
- The released CPython source tree contains generated files; building should not require regenerating them.
- Compatibility work should start with selected translation units and grow into full-tree builds only after the core compiler is ready.

## Language features observed in CPython

The compiler must support the C11 features that CPython relies on, including:

- Standard integer and floating point types.
- `static inline` functions and macros used in headers.
- Designated initializers and compound literals.
- Strict aliasing and volatile semantics where the standard requires it.
- Selected GNU/Clang compatibility spellings that appear in CPython-adjacent SDK headers, such as `__attribute__`, `__thread`, `typeof`, `typeof_unqual`, and `__int128_t`.

## Compatibility targets

- Core runtime (first long-term target).
- Standard library modules written in C (next validation tier).
- Optional third party extension modules (not required for the core compatibility target).

## References

- CPython build requirements and configuration guide (Python docs).
- PEP 7: C language standards and compiler constraints for CPython.
