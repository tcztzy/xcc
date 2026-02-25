# TODO

This file tracks failure-driven work toward the M0 frontend baseline.

## M0 Definition of Done

- [ ] `tox -e py311,lint,type` is green with 0 failures.
- [ ] Coverage is 100% line + branch (`fail-under=100`).
- [ ] Frontend (`preprocess + lex + parse + sema`) succeeds on 10 selected CPython `.c` files without errors.

## Current Blockers

| ID | Category (pp/lex/parse/sema) | Description | Frequency | Status |
| --- | --- | --- | --- | --- |
| B001 | parse | Expected `;` (examples: `typeof_expression`, `double_underscore_typeof_expression`, `nested_function_pointer_declarator`) | 4 / 108 | [ ] |
| B002 | parse | Expected identifier before `;` (examples: `anonymous_struct_union`, `anonymous_struct_in_union`) | 3 / 108 | [ ] |
| B003 | parse | Unknown declaration type name: `__attribute__` (examples: `attribute_visibility_variable`, `attribute_cold_hot`) | 3 / 108 | [ ] |
| B004 | parse | Array size is required in this context (examples: `flexible_array_member`, `flexible_array_embedded`) | 2 / 108 | [ ] |
| B005 | parse | Expected `]` (examples: `array_designator_range_gnu`, `designator_range_with_trailing_comma`) | 2 / 108 | [ ] |
| B006 | parse | Expression cannot start with keyword `struct`: expected an operand (examples: `builtin_offsetof_pattern`, `builtin_offsetof_nested_member`) | 2 / 108 | [ ] |
| B007 | parse | Unknown declaration type name: `a` (examples: `knr_style_function_definition`, `old_style_declaration_plus_definition`) | 2 / 108 | [ ] |
| B008 | parse | Array size must be positive (examples: `zero_length_array_gnu`) | 1 / 108 | [ ] |
| B009 | parse | Expected member declaration (examples: `empty_struct_gnu`) | 1 / 108 | [ ] |
| B010 | sema | Initializer index out of range (examples: `labels_as_values_array`, `computed_goto_loop`) | 2 / 108 | [ ] |
| B011 | sema | Duplicate declaration: `py_counter` (examples: `extern_declaration_then_definition`) | 1 / 108 | [ ] |
| B012 | sema | Duplicate declaration: `tls_counter` (examples: `thread_local_extern_pattern`) | 1 / 108 | [ ] |
| B013 | sema | Duplicate definition: `struct _object` (examples: `typedef_pyobject`) | 1 / 108 | [ ] |
| B014 | sema | Undeclared function: `WRAP` (examples: `complex_macro_multiline_nested`) | 1 / 108 | [ ] |
| B015 | sema | Undeclared function: `__builtin_expect` (examples: `builtin_expect_pattern`) | 1 / 108 | [ ] |
| B016 | sema | Undeclared function: `__builtin_unreachable` (examples: `builtin_unreachable_pattern`) | 1 / 108 | [ ] |
| B017 | sema | Variable length array not allowed at file scope (examples: `initializer_trailing_commas`) | 1 / 108 | [ ] |

## Backlog (reference)

<details>
<summary>Legacy detailed TODO items (1.1 through 3)</summary>

### 1.1 Preprocessor Conformance

- [ ] Close remaining C11 edge cases for macro replacement order and rescanning behavior.
- [x] Iteration 3: tighten conditional expression evaluation parity for `#if` / `#elif` boolean short-circuit corner cases.
- [x] Add `__has_include("...")` / `__has_include(<...>)` conditional support with regression tests.
- [ ] Expand include behavior coverage (path search precedence, diagnostics consistency, mapping interaction).
- [ ] Validate predefined macro behavior against C11 and target assumptions.
- [ ] Add curated fixture cases for every preprocessor diagnostic path.

### 1.2 Lexer Completeness

- [ ] Audit tokenization parity for all C11 literal forms and suffix combinations.
- [ ] Tighten UCN/escape handling in edge cases and ensure diagnostic stability.
- [ ] Expand tests for translation phases interaction (trigraphs + line splicing + comments + literals).
- [ ] Ensure strict/gnu mode split is consistent for extension-sensitive tokens.

### 1.3 Parser Grammar Coverage

- [ ] Remove remaining "unsupported" declarator/array-size parse paths where C11 requires support.
- [ ] Finish full declarator coverage for function pointers, parameter arrays, qualifiers, and nested forms.
- [ ] Complete initialization grammar parity (designators, nested initializer lists, mixed forms).
- [ ] Validate all statement/expression grammar branches against curated fixture corpus.
- [ ] Add targeted negative tests for grammar ambiguity and recovery diagnostics.

### 1.4 Type System Model

- [ ] Implement first-class qualifier model (top-level vs nested qualifiers across all derived types).
- [ ] Complete atomic/qualified/derived type composition rules.
- [ ] Ensure complete/incomplete type transitions are modeled consistently (records, arrays, enums).
- [ ] Normalize type identity/equivalence rules used by parser, sema, and `_Generic` selection.

### 1.5 Semantic Analysis and Conversions

- [ ] Remove remaining `Unsupported statement` / `Unsupported expression` paths by implementing required branches.
- [ ] Complete usual arithmetic conversions and integer promotions for all C11 combinations.
- [x] Iteration 1: align compound-assignment conversion rules with C11 arithmetic/integer constraints (`+=`, `-=`, `*=`, `/=`, `%=` and bit/shift assigns).
- [x] Iteration 2: tighten pointer compatibility for subtraction/relational operations across qualified compatible pointee types and reject `void*` arithmetic.
- [x] Iteration 2b: tighten assignment/equality/conditional/call-pointer conversions for nested qualifier mismatches (e.g. `int **` vs `const int **`).
- [ ] Tighten pointer compatibility/conversion rules (assignment, conditional, equality, call arguments).
- [ ] Complete assignment and initialization constraint checks for all object categories.
- [ ] Finish storage-duration/linkage/storage-class rule enforcement (`extern`/`static`/`_Thread_local`, etc.).
- [ ] Expand control-flow validation (`goto` labels, switch/case constraints, function-scope interactions).
- [ ] Verify constant-expression evaluator against enum, case label, and static assertion requirements.

### 1.6 Declarations and Objects

- [ ] Complete `_Alignas` / `_Alignof` rule handling across declaration contexts.
- [ ] Finalize `_Atomic` object/type constraints and diagnostics.
- [ ] Complete record/union member constraints and layout-relevant semantic validation.
- [ ] Ensure function declaration compatibility checks fully match C11 redeclaration rules.

### 1.7 Diagnostics Quality

- [ ] Ensure each semantic/parse/preprocessor rejection path has stable, actionable messages.
- [ ] Standardize source range and stage-tag behavior for all diagnostics.
- [ ] Add regression tests for all known high-risk diagnostics.

### 1.8 Conformance and Regression Testing

- [ ] Expand curated Clang fixture manifest with additional C11 frontend coverage.
- [ ] Add local tests for every gap where no suitable upstream fixture exists.
- [ ] Maintain 100% line + branch coverage while adding new behavior.
- [ ] Keep `tox -e py311`, `tox -e lint`, `tox -e type`, and `tox -e clang_suite` green.

### 1.9 CPython-Driven Gap Closure

- [ ] Start regular frontend-only compilation trials against selected CPython translation units.
- [ ] Record failures into categorized buckets (preprocessor, parser, sema, diagnostics).
- [ ] Convert each bucket item into reproducible unit/fixture tests before implementation.

## 2. Backend and Toolchain (Outline Only)

- [ ] Define IR shape and lowering contract from frontend typed AST.
- [ ] Implement minimal code generation for macOS arm64 object output.
- [ ] Add Mach-O emission + system linker integration.
- [ ] Add Linux/ELF emission path and mold integration.
- [ ] Validate glibc/musl workflows in Docker tox targets.
- [ ] Build backend diagnostics and debug-info strategy.

## 3. Cross-Cutting Engineering

- [ ] Preserve stdlib-only runtime dependency policy.
- [ ] Keep CPython 3.11+ and PyPy 3.11+ compatibility in CI/tox coverage.
- [ ] Track lessons learned in `LESSONS.md` for each major compiler/testing change.
- [ ] Keep docs in sync with implementation status after each milestone.

</details>
