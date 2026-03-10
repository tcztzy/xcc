# CPython Compatibility

## Scope

The primary milestone is to compile the CPython source tree for a supported platform without modifying CPython sources. The compiler must be compatible with CPython's supported C standard and build requirements.

## Build system interaction

- The compiler must work with CPython's existing build system and flags.
- The released CPython source tree contains generated files; building should not require regenerating them.
- The preview release also tracks a smaller compile-only acceptance step against a pinned CPython source archive.

## Preview acceptance step

- `scripts/cpython_trial.py` covers curated CPython-style snippets.
- `scripts/cpython_file_trial.py` runs compile-only frontend validation against a pinned CPython tarball and a small set of real source files.
- The real-file trial uses the host Python `pyconfig.h` as a local overlay so the trial can run without a full `./configure` step.

## Language features observed in CPython

The compiler must support the C11 features that CPython relies on, including:

- Standard integer and floating point types.
- `static inline` functions and macros used in headers.
- Designated initializers and compound literals.
- Strict aliasing and volatile semantics where the standard requires it.

## Compatibility targets

- Core runtime (required).
- Standard library modules written in C (required for parity testing).
- Optional third party extension modules (not required for initial milestones).

## References

- CPython build requirements and configuration guide (Python docs).
- PEP 7: C language standards and compiler constraints for CPython.
