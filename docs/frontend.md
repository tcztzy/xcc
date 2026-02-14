# Front End

## Overview

The front end currently provides a deterministic check pipeline:

1. Source loading (`file` or `stdin`).
2. Lexing into C tokens.
3. Parsing into the AST.
4. Semantic analysis and type checking.

The pipeline is exposed through `xcc.frontend.compile_source` and used by the CLI entrypoint.

## Driver behavior

The `xcc` CLI runs the front end and exits non-zero on diagnostics.

- `xcc <path.c>`: run front-end checks and print a success marker.
- `xcc -`: read source from standard input.
- `xcc --dump-tokens <path.c>`: print token stream.
- `xcc --dump-ast <path.c>`: print parsed AST.
- `xcc --dump-sema <path.c>`: print semantic model.

Diagnostics are stage-tagged (`lex`, `parse`, `sema`) and include source coordinates when available.

## Language modes

- `c11` is strict mode. GNU-only constructs are rejected, including statement expressions,
  computed goto (`goto *expr`, `&&label`), and GNU asm forms.
- `gnu11` keeps GNU extensions that are currently supported by the front end.

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
- Handles unary, binary, conditional, cast, and enum-constant forms used by the current front-end checks.

## References

- ISO C11 draft (N1570) for language rules and translation phases.
