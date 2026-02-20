# TODO

This file tracks remaining work toward a production-ready C11 compiler. It includes both frontend and backend scope, but only the frontend section is expanded for now.

## 0. Milestone View

- [ ] M0: Complete C11 frontend conformance baseline.
- [ ] M1: Add minimal IR and code generation for macOS arm64.
- [ ] M2: Add Linux/ELF backend path (mold + glibc/musl).
- [ ] M3: Compile CPython core with no source modifications.
- [ ] M4: Harden diagnostics, compatibility, and performance.

## 1. Frontend (Expanded)

### 1.1 Preprocessor Conformance

- [ ] Close remaining C11 edge cases for macro replacement order and rescanning behavior.
- [ ] Tighten conditional expression evaluation parity for `#if` / `#elif` corner cases.
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

## Progress Log

- Iteration: `codex/m0-conversion-01`
- Done:
  - compound assignment accepts arithmetic operands for `*=`, `/=`, `+=`, `-=` and keeps integer-only checks for `%=` / bit/shift assigns;
  - pointer subtraction/relational checks now accept qualified-compatible object pointers and reject `void*` subtraction;
  - assignment/argument/equality/conditional paths now reject nested pointer qualifier promotions such as `int **` to `const int **`;
  - Iteration 3 slice: replaced generic sema fallback `Unsupported expression` for unknown binary operators with operator-specific diagnostics (`Unsupported binary operator: <op>`), while preserving supported `BinaryExpr` analysis paths.
  - Iteration 3 slice: replaced generic sema fallback `Unsupported expression` for unknown unary operators with operator-specific diagnostics (`Unsupported unary operator: <op>`), while preserving supported `UnaryExpr` analysis paths.
  - Iteration 3 slice: removed the implicit assignment-operator fallback in sema by validating compound operators explicitly and emitting `Unsupported assignment operator: <op>` for unknown `AssignExpr.op` values.
  - Iteration 3 slice: removed the implicit update-operator fallback in sema by validating `UpdateExpr.op` and emitting `Unsupported update operator: <op>` for unknown update operators.
  - Iteration 3 slice: replaced the generic sema fallback `Unsupported expression` with node-specific diagnostics (`Unsupported expression node: <ExprClass>`), reducing opaque fallback behavior for unsupported expression AST nodes.
  - Iteration 3 slice: removed the shared shift-family fallback diagnostic (`Binary operator requires integer operands`) by adding operand-specific checks for `<<`/`>>` (`Shift left operand must be integer` / `Shift right operand must be integer`).
  - Iteration 3 slice: replaced the generic statement fallback (`Unsupported statement`) with a node-specific diagnostic (`Unsupported statement node: <StmtClass>`), reducing opaque sema failures for unsupported statement AST nodes.
  - Iteration 3 slice: replaced the generic file-scope declaration fallback (`Unsupported file-scope declaration`) with a node-specific diagnostic (`Unsupported file-scope declaration node: <DeclClass>`), improving unsupported top-level declaration diagnostics.
  - Iteration 3 slice: tightened condition validation by enforcing scalar conditions for `if`/`for`/`while`/`do-while`/`?:` and integer conditions for `switch`, with dedicated diagnostics for non-scalar and non-integer cases.
  - Iteration 3 slice: replaced remaining shared multiplicative/modulo/bitwise operand diagnostics with operator- and side-specific checks (`Multiplication/Division/Modulo/Bitwise <left|right> operand ...`) to reduce ambiguous sema failures.
  - Iteration 3 slice: replaced shared equality/logical scalar-operand diagnostics with side-specific messages (`Equality/Logical <left|right> operand must be scalar`) for clearer sema failures.
  - Iteration 3 slice: tightened unary operand constraints and diagnostics by splitting `+`/`-`/`~` checks (`Unary plus/minus operand must be arithmetic`, `Bitwise not operand must be integer`) and allowing floating unary `+`/`-` results.
  - Iteration 3 slice: replaced shared additive diagnostics with operator-specific messages for `+` and `-`, clarifying pointer/integer and pointer-pointer rejection paths.
  - Iteration 3 slice: improved call diagnostics by including expected/got argument counts and 1-based argument index in type mismatch errors.
  - Iteration 3 slice: replaced update-expression generic mismatch diagnostics with a dedicated operand constraint message (`Update operand must be integer or pointer`).
  - Iteration 3 slice: replaced compound-assignment generic mismatch diagnostics with operator-family-specific messages (additive, multiplicative, and bitwise/shift/modulo assignment constraints).
- Remaining risk: full C11 pointer qualification rules still need structural pointer-level qualifier modeling (current `Type` qualifier representation is base-type-centric).
- Next target: start Iteration 3 by reducing remaining `Unsupported statement/expression` fallback paths.
