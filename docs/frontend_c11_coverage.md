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
  - GNU `#elifdef` / `#elifndef` conditional directives.
- **Parser diagnostic hardening (ongoing)**
  - Type-name contexts now reject accidental declarator identifiers with an explicit diagnostic (`Type name cannot declare identifier '...'`) in cast and `_Atomic(type-name)` parsing.
  - `_Alignas(...)` operand validation now reports operand-specific diagnostics under a shared `Invalid alignment specifier: ...` prefix for non-object type operands, non-ICE expression operands, non-positive values, and non-power-of-two values.
  - Local clang parser regression fixtures now cover static-assert expression-start diagnostics directly at the `_Static_assert` condition site (including punctuator/digraph/token-paste starts), with manifest checksum and source-location metadata kept in sync.
- **Sema diagnostic hardening (ongoing)**
  - Function declarations/definitions using `_Thread_local` now emit a declaration-context-specific diagnostic (`Invalid declaration specifier for function declaration: '_Thread_local'`) instead of a generic specifier error.
  - Compound literals now report context-aware invalid object-type diagnostics (`Invalid object type for compound literal: ...`) for `void`, incomplete record, and invalid `_Atomic(...)` object types.
  - `_Generic` association type rejections now report reason-specific diagnostics (`Invalid generic association type: <reason>`) for invalid categories such as `void type`, `atomic type`, `incomplete type`, and `variably modified type`.
  - `_Generic` duplicate-association diagnostics now include source-location context for both the current and prior association when parser metadata is available, keeping duplicate-default and duplicate-compatible-type failures easier to correlate with source entries.
  - `_Generic` no-match, invalid-association-type, duplicate-compatible-type, and duplicate-default diagnostics now fall back to `GenericExpr.association_source_locations` when a `TypeSpec` lacks direct source coordinates, including explicit partial-location formatting (`line N` or `column M`) when only one coordinate is available in manually-constructed AST regression fixtures.
  - Object declarations that misuse `typedef` storage class now report action-oriented diagnostics in both file and block scope (`...; use a typedef declaration instead`) rather than the previous context-ambiguous storage-class rejection.
  - `_Thread_local` object declarations that use invalid or missing block-scope storage classes now report requirement-oriented diagnostics (`...; '_Thread_local' requires 'static' or 'extern'`) so storage-class fixes are explicit.
- **Core preprocessor behavior**
  - Macro expansion (`#define`, function-like, variadic, token paste, stringize).
  - Conditional directives, `defined`, character-literal operands, and include/feature probe operators in `#if`/`#elif` (`__has_include`, `__has_builtin`, `__has_feature`, `__has_extension`, `__has_warning`, `__has_c_attribute`), including macro-expanded operator spellings and operands.
  - `#if`/`#elif` boolean short-circuit evaluation for `&&`/`||` (including divide-by-zero guard cases).
  - Include search precedence is validated (`"..."` prefers source directory, then `-iquote`, then `-I`; `<...>` resolves via `-I`/`-isystem`/`-idirafter` and skips `-iquote`), with cycle/read diagnostics; cycle failures now include the concrete include chain (`a.h -> b.h -> a.h`) for faster root-cause triage.
  - CLI macro-include files (`-imacros <header>`) are processed before forced includes so macro definitions are available to subsequent includes and the main source while non-directive text from macro-include files is discarded.
  - CLI forced-includes (`-include <header>`) are applied before the main source using the same quoted-include search roots and produce dedicated diagnostics when a forced header is missing.
  - Include-not-found diagnostics preserve directive delimiters (`"..."` vs `<...>`) and enumerate searched include roots for faster path-debugging; regression coverage now also checks that both `#include` and GNU `#include_next` failures honor active `#line` filename/line remapping.
  - `#include` now accepts macro-expanded header operands for both quoted and angle forms, with invalid expansion diagnostics covered.
  - GNU mode supports `#include_next` and `__has_include_next(...)`, both continuing include search after the current include directory (including skipping the source directory for quoted includes).
  - `#pragma once` include guards are honored so repeated and nested includes of the same header are skipped after the first expansion.
  - `#line` mapping and diagnostic remapping, including macro-expanded decimal/filename operands.
- **Predefined macro coverage (current)**
  - `__STDC__`, `__STDC_HOSTED__`, `__STDC_VERSION__`, `__STDC_IEC_559__`, `__STDC_MB_MIGHT_NEQ_WC__`, `__STDC_UTF_16__`, `__STDC_UTF_32__`, `__STDC_NO_ATOMICS__`, `__STDC_NO_COMPLEX__`, `__STDC_NO_THREADS__`, `__STDC_NO_VLA__`, `__STDC_ISO_10646__`, `__FILE__`, GNU-compatible `__FILE_NAME__`, `__BASE_FILE__`, `__LINE__`, `__INCLUDE_LEVEL__`, `__COUNTER__`, `__DATE__`, `__TIME__`, GNU-compatible `__TIMESTAMP__`.
  - Mode-specific predefined macro split is covered: strict `c11` defines `__STRICT_ANSI__`, while `gnu11` defines GNU compatibility version macros (`__GNUC__`, `__GNUC_MINOR__`, `__GNUC_PATCHLEVEL__`, `__GNUC_STDC_INLINE__`, `__VERSION__`).
  - Hosted-vs-freestanding assumptions are configurable via CLI (`-fhosted` / `-ffreestanding`) and reflected in `__STDC_HOSTED__` (`1` or `0`).
  - Target-assumption baseline macros for LP64 little-endian hosts are included and regression-tested (`__LP64__`, `__LP64`, `_LP64`, `__CHAR_BIT__`, `__SIZEOF_BOOL__`, `__SIZEOF_SHORT__`, `__SIZEOF_INT__`, `__SIZEOF_POINTER__`, `__SIZEOF_LONG__`, `__SIZEOF_LONG_LONG__`, `__SIZEOF_SIZE_T__`, `__SIZEOF_PTRDIFF_T__`, `__SIZEOF_INTMAX_T__`, `__SIZEOF_UINTMAX_T__`, `__SIZEOF_WCHAR_T__`, `__SIZEOF_WINT_T__`, `__SIZEOF_CHAR16_T__`, `__SIZEOF_CHAR32_T__`, `__ORDER_LITTLE_ENDIAN__`, `__ORDER_BIG_ENDIAN__`, `__BYTE_ORDER__`, `__LITTLE_ENDIAN__`, `__BIG_ENDIAN__`, `__FLOAT_WORD_ORDER__`, `__SIZE_TYPE__`, `__PTRDIFF_TYPE__`, `__INTPTR_TYPE__`, `__UINTPTR_TYPE__`, `__INTMAX_TYPE__`, `__UINTMAX_TYPE__`, `__CHAR16_TYPE__`, `__CHAR32_TYPE__`, fixed-width integer type families `__INT{8,16,32,64}_TYPE__` / `__UINT{8,16,32,64}_TYPE__`, least-width aliases `__INT_LEAST{8,16,32,64}_TYPE__` / `__UINT_LEAST{8,16,32,64}_TYPE__`, fast-width aliases `__INT_FAST{8,16,32,64}_TYPE__` / `__UINT_FAST{8,16,32,64}_TYPE__`, `__WCHAR_TYPE__`, `__WINT_TYPE__`, `__WCHAR_WIDTH__`, `__WINT_WIDTH__`, `__CHAR16_WIDTH__`, `__CHAR32_WIDTH__`, `__WCHAR_MAX__`, `__WCHAR_MIN__`, `__WINT_MAX__`, `__WINT_MIN__`, `__SIG_ATOMIC_TYPE__`, `__SIG_ATOMIC_WIDTH__`, `__SIG_ATOMIC_MAX__`, `__SIG_ATOMIC_MIN__`).
  - Integer width/value assumptions are also predefined and regression-tested (`__INT_WIDTH__`, `__LONG_WIDTH__`, `__LONG_LONG_WIDTH__`, `__LLONG_WIDTH__`, `__INTMAX_WIDTH__`, `__UINTMAX_WIDTH__`, `__SIZE_WIDTH__`, `__PTRDIFF_WIDTH__`, `__INTPTR_WIDTH__`, `__UINTPTR_WIDTH__`, `__POINTER_WIDTH__`, `__BOOL_WIDTH__`, `__SCHAR_MAX__`, `__SCHAR_MIN__`, `__SHRT_MAX__`, `__SHRT_MIN__`, `__INT_MAX__`, `__INT_MIN__`, `__LONG_MAX__`, `__LONG_MIN__`, `__LONG_LONG_MAX__`, `__LONG_LONG_MIN__`, `__LLONG_MAX__`, `__LLONG_MIN__`, `__INTMAX_MAX__`, `__INTMAX_MIN__`, `__INTPTR_MAX__`, `__INTPTR_MIN__`, `__UCHAR_MAX__`, `__USHRT_MAX__`, `__UINT_MAX__`, `__ULONG_MAX__`, `__ULLONG_MAX__`, `__SIZE_MAX__`, `__PTRDIFF_MAX__`, `__PTRDIFF_MIN__`, `__UINTPTR_MAX__`, `__UINTMAX_MAX__`, integer-constructor macro families `__INT{8,16,32,64}_C(value)` / `__UINT{8,16,32,64}_C(value)` and `__INTMAX_C(value)` / `__UINTMAX_C(value)` with LP64-consistent `L`/`UL` suffix expansion).
  - GCC compatibility atomics/sync predefined macros are also modeled and regression-tested (`__ATOMIC_{RELAXED,CONSUME,ACQUIRE,RELEASE,ACQ_REL,SEQ_CST}`, `__GCC_ATOMIC_{BOOL,CHAR,SHORT,INT,LONG,LLONG,POINTER,CHAR16_T,CHAR32_T,WCHAR_T}_LOCK_FREE`, `__GCC_ATOMIC_TEST_AND_SET_TRUEVAL`, `__GCC_HAVE_SYNC_COMPARE_AND_SWAP_{1,2,4,8,16}`).
  - Floating-format target assumptions are predefined and regression-tested (`__FLT_RADIX__`, `__FLT_MANT_DIG__`, `__DBL_MANT_DIG__`, `__LDBL_MANT_DIG__`, `__FLT_DIG__`, `__DBL_DIG__`, `__LDBL_DIG__`, `__FLT_DECIMAL_DIG__`, `__DBL_DECIMAL_DIG__`, `__LDBL_DECIMAL_DIG__`, `__DECIMAL_DIG__`, `__FLT_EPSILON__`, `__DBL_EPSILON__`, `__LDBL_EPSILON__`, `__FLT_MIN__`, `__DBL_MIN__`, `__LDBL_MIN__`, `__FLT_DENORM_MIN__`, `__DBL_DENORM_MIN__`, `__LDBL_DENORM_MIN__`, `__FLT_MAX__`, `__DBL_MAX__`, `__LDBL_MAX__`, `__FLT_MIN_EXP__`, `__DBL_MIN_EXP__`, `__LDBL_MIN_EXP__`, `__FLT_MIN_10_EXP__`, `__DBL_MIN_10_EXP__`, `__LDBL_MIN_10_EXP__`, `__FLT_MAX_EXP__`, `__DBL_MAX_EXP__`, `__LDBL_MAX_EXP__`, `__FLT_MAX_10_EXP__`, `__DBL_MAX_10_EXP__`, `__LDBL_MAX_10_EXP__`, `__FLT_HAS_DENORM__`, `__DBL_HAS_DENORM__`, `__LDBL_HAS_DENORM__`, `__FLT_HAS_INFINITY__`, `__DBL_HAS_INFINITY__`, `__LDBL_HAS_INFINITY__`, `__FLT_HAS_QUIET_NAN__`, `__DBL_HAS_QUIET_NAN__`, `__LDBL_HAS_QUIET_NAN__`).
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
