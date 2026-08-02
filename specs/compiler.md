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
