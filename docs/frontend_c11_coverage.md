# Front End C11 Coverage

## Scope

This document tracks C11 front-end coverage for the current implementation. It is intended as a
living checklist for parser/sema/preprocessor behavior and regression tests.

## Implemented and tested

- **Language mode split**
  - `c11` rejects GNU-only constructs.
  - `gnu11` accepts currently supported GNU constructs.
- **GNU-only constructs gated by mode**
  - Statement expressions.
  - Computed goto and label-address expressions.
  - GNU asm statement and asm label forms in preprocessing.
- **Parser diagnostic hardening (ongoing)**
  - Type-name contexts now reject accidental declarator identifiers with an explicit diagnostic (`Type name cannot declare identifier '...'`) in cast and `_Atomic(type-name)` parsing.
  - `_Alignas(...)` operand validation now reports operand-specific diagnostics for non-object type operands, non-ICE expression operands, non-positive values, and non-power-of-two values.
- **Sema diagnostic hardening (ongoing)**
  - Function declarations/definitions using `_Thread_local` now emit a declaration-context-specific diagnostic (`Invalid declaration specifier for function declaration: '_Thread_local'`) instead of a generic specifier error.
  - Compound literals now report context-aware invalid object-type diagnostics (`Invalid object type for compound literal: ...`) for `void`, incomplete record, and invalid `_Atomic(...)` object types.
  - `_Generic` association type rejections now report reason-specific diagnostics (`Invalid generic association type: <reason>`) for invalid categories such as `void type`, `atomic type`, `incomplete type`, and `variably modified type`.
- **Core preprocessor behavior**
  - Macro expansion (`#define`, function-like, variadic, token paste, stringize).
  - Conditional directives, `defined`, and `__has_include` checks in `#if`/`#elif` (including macro-expanded header operands).
  - `#if`/`#elif` boolean short-circuit evaluation for `&&`/`||` (including divide-by-zero guard cases).
  - Include search precedence is validated (`"..."` prefers source directory, then `-iquote`, then `-I`; `<...>` resolves via `-I`/`-isystem`/`-idirafter` and skips `-iquote`), with cycle/read diagnostics; cycle failures now include the concrete include chain (`a.h -> b.h -> a.h`) for faster root-cause triage.
  - CLI macro-include files (`-imacros <header>`) are processed before forced includes so macro definitions are available to subsequent includes and the main source while non-directive text from macro-include files is discarded.
  - CLI forced-includes (`-include <header>`) are applied before the main source using the same quoted-include search roots and produce dedicated diagnostics when a forced header is missing.
  - Include-not-found diagnostics preserve directive delimiters (`"..."` vs `<...>`) and now enumerate the searched include roots for faster path-debugging; include expansion line-map provenance is regression-tested.
  - `#include` now accepts macro-expanded header operands for both quoted and angle forms, with invalid expansion diagnostics covered.
  - GNU mode supports `#include_next` and `__has_include_next(...)`, both continuing include search after the current include directory (including skipping the source directory for quoted includes).
  - `#pragma once` include guards are honored so repeated and nested includes of the same header are skipped after the first expansion.
  - `#line` mapping and diagnostic remapping, including macro-expanded decimal/filename operands.
- **Predefined macro coverage (current)**
  - `__STDC__`, `__STDC_HOSTED__`, `__STDC_VERSION__`, `__STDC_IEC_559__`, `__STDC_MB_MIGHT_NEQ_WC__`, `__STDC_UTF_16__`, `__STDC_UTF_32__`, `__STDC_NO_ATOMICS__`, `__STDC_NO_COMPLEX__`, `__STDC_NO_THREADS__`, `__STDC_NO_VLA__`, `__STDC_ISO_10646__`, `__FILE__`, GNU-compatible `__FILE_NAME__`, `__BASE_FILE__`, `__LINE__`, `__INCLUDE_LEVEL__`, `__COUNTER__`, `__DATE__`, `__TIME__`, GNU-compatible `__TIMESTAMP__`.
  - Target-assumption baseline macros for LP64 little-endian hosts are included and regression-tested (`__LP64__`, `__LP64`, `_LP64`, `__CHAR_BIT__`, `__SIZEOF_SHORT__`, `__SIZEOF_INT__`, `__SIZEOF_POINTER__`, `__SIZEOF_LONG__`, `__SIZEOF_LONG_LONG__`, `__SIZEOF_SIZE_T__`, `__SIZEOF_PTRDIFF_T__`, `__SIZEOF_INTMAX_T__`, `__SIZEOF_UINTMAX_T__`, `__SIZEOF_WCHAR_T__`, `__SIZEOF_WINT_T__`, `__ORDER_LITTLE_ENDIAN__`, `__ORDER_BIG_ENDIAN__`, `__BYTE_ORDER__`, `__LITTLE_ENDIAN__`, `__BIG_ENDIAN__`, `__FLOAT_WORD_ORDER__`, `__SIZE_TYPE__`, `__PTRDIFF_TYPE__`, `__INTPTR_TYPE__`, `__UINTPTR_TYPE__`, `__WCHAR_TYPE__`, `__WINT_TYPE__`, `__WCHAR_WIDTH__`, `__WINT_WIDTH__`, `__WCHAR_MAX__`, `__WCHAR_MIN__`, `__WINT_MAX__`, `__WINT_MIN__`, `__SIG_ATOMIC_TYPE__`, `__SIG_ATOMIC_WIDTH__`, `__SIG_ATOMIC_MAX__`, `__SIG_ATOMIC_MIN__`).
  - Integer width/value assumptions are also predefined and regression-tested (`__INT_WIDTH__`, `__LONG_WIDTH__`, `__LONG_LONG_WIDTH__`, `__INTMAX_WIDTH__`, `__UINTMAX_WIDTH__`, `__SIZE_WIDTH__`, `__PTRDIFF_WIDTH__`, `__INTPTR_WIDTH__`, `__UINTPTR_WIDTH__`, `__SCHAR_MAX__`, `__SCHAR_MIN__`, `__SHRT_MAX__`, `__SHRT_MIN__`, `__INT_MAX__`, `__INT_MIN__`, `__LONG_MAX__`, `__LONG_MIN__`, `__LONG_LONG_MAX__`, `__LONG_LONG_MIN__`, `__INTMAX_MAX__`, `__INTMAX_MIN__`, `__INTPTR_MAX__`, `__INTPTR_MIN__`, `__UCHAR_MAX__`, `__USHRT_MAX__`, `__UINT_MAX__`, `__ULONG_MAX__`, `__SIZE_MAX__`, `__PTRDIFF_MAX__`, `__PTRDIFF_MIN__`, `__UINTPTR_MAX__`, `__UINTMAX_MAX__`).
  - Builtin-only preprocessing preserves original line spelling when a line does not reference a macro (no retokenization side effects from predefined macro setup).

## Partially covered / pending

- **Full C11 type qualifier model**
  - Top-level and nested qualifiers are not yet modeled as a first-class structured type system.
- **Full C11 conversion model**
  - Expression result typing for all arithmetic combinations still uses simplified paths.
- **Preprocessor conformance edge cases**
  - Behavior is sufficient for current tests but not a complete C11 preprocessor conformance claim.

## Acceptance gate

All of the following must remain green:

- `tox -e py311`
- `tox -e lint`
- `tox -e type`
- `tox -e clang_suite`

Coverage policy remains **100% line + branch** for the Python source tree.
