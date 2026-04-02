# Architecture

## Pipeline overview

1. CLI parsing and driver/frontend mode selection.
2. Source loading, option normalization, and include-root setup.
3. Preprocessing and macro expansion.
4. Lexing and parsing into an AST.
5. Semantic analysis and type checking.
6. Direct lowering from the typed AST to AArch64 assembly for the macOS `arm64` backend implementation that exists today.
7. Assembly and linking via the system `clang` toolchain, or full `clang` delegation when requested.

## Core design choices

- Deterministic output for a given input and configuration.
- Small, testable components with clear interfaces.
- Explicit error reporting with source ranges and actionable messages.
- No hidden global state outside a controlled compilation context.

## Module boundaries

- `xcc.__init__` and `cc_driver`: CLI parsing, driver orchestration, backend selection, and `clang` delegation.
- `frontend`: source loading plus preprocess/lex/parse/sema orchestration.
- `options`: frontend option model and normalization.
- `preprocessor`: tokens, macros, include handling.
- `lexer`: translation phases and token classification.
- `parser`: grammar, AST nodes.
- `sema`: types, scopes, constant evaluation.
- `codegen`: direct native lowering to assembly.
- `host_includes`: host toolchain include-root discovery for driver mode.
- `clang_suite`: shared helpers for the pinned LLVM/Clang baseline.
- `diag`: diagnostics and formatting.

## Diagnostics strategy

- Single source of truth for diagnostic codes.
- Errors are structured data, with rendering separated from detection.
- Every diagnostic path is covered by unit tests.
