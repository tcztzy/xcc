# Front End

## Overview

The compiler front end provides a deterministic check pipeline:

1. Source loading (`file` or `stdin`).
2. Preprocessing, macro expansion, and include resolution.
3. Lexing into C tokens.
4. Parsing into the AST.
5. Semantic analysis and type checking.

The pipeline is exposed through `xcc.frontend.compile_source` / `compile_path` and is used by both the frontend-only CLI mode and the compile driver.

## Driver behavior

The `xcc` CLI has two entry modes:

- `xcc <path.c>`: driver mode. Run the full frontend, then either use the native backend or delegate to `clang`.
- `xcc --frontend <path.c>`: frontend-only mode. Run preprocess/lex/parse/sema and print a success marker or the requested dumps.
- `xcc -`: read source from standard input.
- `xcc --frontend --dump-pp-tokens <path.c>`: print the preprocessor token stream.
- `xcc --frontend --dump-include-trace <path.c>`: print include resolution trace.
- `xcc --frontend --dump-macro-table <path.c>`: print the final macro table.
- `xcc --frontend --dump-tokens <path.c>`: print token stream.
- `xcc --frontend --dump-ast <path.c>`: print parsed AST.
- `xcc --frontend --dump-sema <path.c>`: print semantic model.
- `xcc --backend={auto,xcc,clang}`: select driver backend behavior for C compile inputs.
- `xcc --no-backend-fallback`: keep `--backend=auto` strict instead of falling back to `clang`.
- `xcc -S`, `-c`, `-o`: use standard compile-driver output controls.
- `xcc -I <dir>`, `-iquote <dir>`, `-isystem <dir>`, `-idirafter <dir>`: configure include search roots.
- `CPATH` and `C_INCLUDE_PATH`: environment include roots used after `-I` and `-isystem` respectively (empty entries map to the current working directory, matching GCC/Clang behavior).
- `xcc -nostdinc`: disable `CPATH` and `C_INCLUDE_PATH` during include resolution (explicit CLI include paths still apply).
- `xcc -include <header>`: force-include a header before the main translation unit (repeatable).
- `xcc -imacros <header>`: load macros from a header before preprocessing the main translation unit, while discarding that header's non-directive output (repeatable).
- `xcc -fhosted` / `xcc -ffreestanding`: set hosted-environment assumptions by defining `__STDC_HOSTED__` to `1` or `0`.
- `xcc --frontend --diag-format=json`: emit structured frontend diagnostics.

Diagnostics are stage-tagged (`lex`, `parse`, `sema`) and include source coordinates when available.
Unexpected internal AST-shape failures in semantic analysis (including expression/statement and file-scope declaration fallbacks) are surfaced as explicit internal sema bug diagnostics, so frontend gaps are immediately distinguishable from user-code constraint violations.

## Language modes

- `c11` is strict mode. GNU-only constructs are rejected, including statement expressions,
  computed goto (`goto *expr`, `&&label`), and GNU asm forms.
- `gnu11` keeps GNU extensions currently supported by XCC, including
  GNU preprocessor conditionals like `#elifdef` / `#elifndef`.

## Lexer

- Follows C11 tokenization with translation-phase newline normalization, trigraph replacement, and line splicing.
- Supports comments, keywords, punctuators, numeric constants, character/string literals, and universal character names.
- Supports preprocessing token mode (`PP_NUMBER`, header name tokenization).

## Parser

- Builds a typed AST using a recursive descent parser.
- Covers declarations, function definitions/declarations, record/enum declarations, control flow statements, and expressions.
- Supports declarator forms needed for pointers, arrays, and function/function-pointer declarations.
- Supports canonical integer type-specifier combinations for `char`/`short`/`int`/`long`/`long long` with `signed` and `unsigned`.

## Semantic analysis

- Builds scopes for objects, typedef names, enums, and functions.
- Resolves expression types and validates assignments, calls, control-flow contexts, and declaration constraints.
- Evaluates integer constant expressions for enum values and `case` labels.

## Constant evaluation

- Supports deterministic integer constant expression evaluation for required semantic checks.
- Handles unary, binary, conditional, cast, and enum-constant forms used by the current compiler checks.

## References

- ISO C11 draft (N1570) for language rules and translation phases.
