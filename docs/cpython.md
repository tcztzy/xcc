# CPython Compatibility

## Scope

XCC targets compiling the CPython source tree for supported platforms without modifying CPython sources. The compiler must be compatible with CPython's supported C standard and build requirements.

## Build system interaction

- The compiler must work with CPython's existing build system and flags.
- The released CPython source tree contains generated files; building should not require regenerating them.
- The current acceptance path combines the CPython integration gate with detailed compile-only checks against a pinned CPython source archive.

## Current acceptance step

- `scripts/cpython_trial.py` reports the CPython integration gate verdict and top blocker bucket.
- `scripts/cpython_file_trial.py` runs detailed compile-only validation against a pinned CPython 3.11.12 tarball and a curated set of real source files.
- The real-file trial uses the host Python `pyconfig.h` as a local overlay so the trial can run without a full `./configure` step.

## Language features observed in CPython

The compiler must support the C11 features that CPython relies on, including:

- Standard integer and floating point types.
- `static inline` functions and macros used in headers.
- Designated initializers and compound literals.
- Strict aliasing and volatile semantics where the standard requires it.
- Selected GNU/Clang compatibility spellings that appear in CPython-adjacent SDK headers, such as `__attribute__`, `__thread`, `typeof`, `typeof_unqual`, and `__int128_t`.

## Compatibility targets

- Core runtime (required).
- Standard library modules written in C (required for parity testing).
- Optional third party extension modules (not required for the core compatibility target).

## References

- CPython build requirements and configuration guide (Python docs).
- PEP 7: C language standards and compiler constraints for CPython.
