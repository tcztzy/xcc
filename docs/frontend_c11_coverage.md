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
- **Sema diagnostic hardening (ongoing)**
  - Function declarations/definitions using `_Thread_local` now emit a declaration-context-specific diagnostic (`Invalid declaration specifier for function declaration: '_Thread_local'`) instead of a generic specifier error.
- **Core preprocessor behavior**
  - Macro expansion (`#define`, function-like, variadic, token paste, stringize).
  - Conditional directives, `defined`, and `__has_include` checks in `#if`/`#elif` (including macro-expanded header operands).
  - `#if`/`#elif` boolean short-circuit evaluation for `&&`/`||` (including divide-by-zero guard cases).
  - Include search precedence is validated (`"..."` prefers source directory; `<...>` resolves via include paths), with cycle/read diagnostics.
  - Include-not-found diagnostics preserve directive delimiters (`"..."` vs `<...>`), and include expansion line-map provenance is regression-tested.
  - `#include` now accepts macro-expanded header operands for both quoted and angle forms, with invalid expansion diagnostics covered.
  - `#pragma once` include guards are honored so repeated and nested includes of the same header are skipped after the first expansion.
  - `#line` mapping and diagnostic remapping.
- **Predefined macro coverage (current)**
  - `__STDC__`, `__STDC_HOSTED__`, `__STDC_VERSION__`, `__STDC_UTF_16__`, `__STDC_UTF_32__`, `__FILE__`, `__LINE__`, `__DATE__`, `__TIME__`.
  - Integer width/value macros already used by tests.
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
