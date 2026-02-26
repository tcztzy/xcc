# Architecture

## Pipeline overview

1. Source management and build driver.
2. Preprocessing and macro expansion.
3. Lexing and parsing into an AST.
4. Semantic analysis and type checking.
5. IR construction and optimization.
6. Code generation and object emission.
7. Linker integration and final artifacts.

## Core design choices

- Deterministic output for a given input and configuration.
- Small, testable components with clear interfaces.
- Explicit error reporting with source ranges and actionable messages.
- No hidden global state outside a controlled compilation context.

## Module boundaries

- `driver`: CLI, file graph, dependency tracking.
- `preprocessor`: tokens, macros, include handling.
- `parser`: grammar, AST nodes.
- `sema`: types, scopes, constant evaluation.
- `ir`: SSA or structured IR with explicit control flow.
- `codegen`: target backend and object emission.
- `diag`: diagnostics and formatting.

## Diagnostics strategy

- Single source of truth for diagnostic codes.
- Errors are structured data, with rendering separated from detection.
- Every diagnostic path is covered by unit tests.
