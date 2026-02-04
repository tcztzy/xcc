# Front End

## Preprocessor

- Implement standard macro expansion and include search rules.
- Track source locations through macro expansion for diagnostics.
- Preserve comments only when required for line mapping and pragmas.

## Lexer

- Follow the C11 tokenization rules, including preprocessing numbers and universal character names.
- Maintain exact spelling for diagnostics and reproducible output.

## Parser

- Implement a full C11 grammar with extensions explicitly gated and documented.
- Favor a clear, testable recursive descent or Pratt style parser with explicit precedence.

## Semantic analysis

- Implement full C11 type system rules, including integer promotions, usual arithmetic conversions, and composite types.
- Build symbol tables with explicit lifetime and storage duration tracking.
- Enforce constraints for declarations, initializers, and control flow.

## Constant evaluation

- Support C11 integer constant expressions and required arithmetic.
- Provide deterministic evaluation with overflow rules matching the standard.

## References

- ISO C11 draft (N1570) for language rules and translation phases.
