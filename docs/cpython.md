# CPython Compatibility

## Scope

The primary milestone is to compile the CPython source tree for a supported platform without modifying CPython sources. The compiler must be compatible with CPython's supported C standard and build requirements.

## Build system interaction

- The compiler must work with CPython's existing build system and flags.
- The released CPython source tree contains generated files; building should not require regenerating them.

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
