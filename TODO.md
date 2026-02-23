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
  - Iteration 3 slice: replaced plain assignment mismatch diagnostics with an explicit compatibility message (`Assignment value is not compatible with target type`).
  - Iteration 3 slice: replaced return mismatch diagnostics with an explicit compatibility message (`Return value is not compatible with function return type`).
  - Iteration 3 slice: split cast rejection diagnostics into target, operand, and overload-selection failures for clearer cast errors.
  - Iteration 3 slice: equality now treats casted null pointer constants (`(void*)0`) as null-pointer-compatible even in pointer-vs-pointer comparisons (including function pointers), while preserving existing incompatible pointer diagnostics.
  - Iteration 3 slice: tightened pointer arithmetic constraints so additive/compound-additive/update expressions reject `void*` and function-pointer arithmetic (`+`, `-`, `+=`, `-=`, `++`, `--`) while preserving object-pointer arithmetic.
  - Iteration 3 slice: split scalar/array/record initializer-list designator diagnostics into shape-specific messages (scalar single-item/designator rules and array/member designator kind requirements).
  - Iteration 3 slice: made preprocessor `#if` expression fallback diagnostics node/operator-specific in both evaluators (preprocessor and integer-expression paths), and added regression assertions for the exact error text.
  - Iteration 3 slice: split generic preprocessor/integer-expression literal fallback diagnostics into literal-type-specific messages and added comparator-shape regression coverage for both evaluators.
  - Iteration 3 slice: split parser generic `Unsupported type` diagnostics into context-specific messages (`Unsupported declaration type` vs `Unsupported type name`) and added parser/fixture coverage updates.
  - Iteration 3 slice: split integer type-specifier fallback diagnostics into specific parser errors for duplicate signedness and invalid keyword ordering, with regression coverage for declaration/type-name contexts.
  - Iteration 3 slice: made duplicate storage-class declaration-specifier diagnostics keyword-specific (`Duplicate storage class specifier: '<keyword>'`) and updated parser regression coverage.
  - Iteration 3 slice: made duplicate thread-local declaration-specifier diagnostics keyword-specific (`Duplicate thread-local specifier: '_Thread_local'`) and updated parser regression coverage.
  - Iteration 3 slice: tightened parameter-array declaration diagnostics by rejecting duplicate array qualifiers (`Duplicate type qualifier: '<keyword>'`) and duplicate `static` bounds (`Duplicate array bound specifier: 'static'`), with parser regression coverage updates.
  - Iteration 3 slice: split generic parser array-size fallback diagnostics into context-specific messages (`Array size is required in this context` and `Array size must be an integer constant expression`) and tightened parser regression assertions for these paths.
  - Iteration 3 slice: replaced the generic static-parameter array-size helper error (`Expected array size`) with a context-specific diagnostic (`Array parameter with 'static' requires a size`) and added focused parser regression coverage.
  - Iteration 3 slice: split array-size integer-literal parse failures into source-shape-specific parser diagnostics (`unsupported integer suffix`, `non-octal digits`, `hex literal requires at least one digit`, `decimal digits required`) and expanded parser regression assertions for helper/declarator paths.
  - Iteration 3 slice: replaced the generic non-VLA array-size constant-expression fallback with expression-node-specific diagnostics (`Array size expression '<ExprClass>' is not an integer constant expression`) and expanded parser regression coverage for malformed literal-token and suffix-only decimal-shape branches.
  - Iteration 3 slice: refined array-size non-ICE diagnostics for cast and conditional expressions by reporting conditional-condition failures directly and unwrapping cast operands to their underlying non-ICE cause, with focused parser regression assertions.
  - Iteration 3 slice: split array-size fallback diagnostics for `sizeof`/`_Alignof` expression forms into dedicated messages (`Array size sizeof expression ...` / `Array size alignof expression ...`) and added focused helper regression coverage.
  - Iteration 3 slice: split array-size non-ICE assignment fallback into a node-specific diagnostic (`Array size assignment expression is not an integer constant expression`) and added focused helper regression coverage.
  - Iteration 3 slice: refined unsupported type-specifier diagnostics by including the offending token text in declaration/type-name contexts (`Unsupported declaration type: '<token>'` / `Unsupported type name: '<token>'`) and updated parser regression assertions.
  - Iteration 3 slice: split unknown-identifier type diagnostics from unsupported-keyword diagnostics (`Unknown declaration type name: '<ident>'` / `Unknown type name: '<ident>'`), and routed generic-association type parsing through type-name context diagnostics.
  - Iteration 3 slice: split unsupported non-keyword type diagnostics into token-category-aware messages (`Unsupported declaration/type name token (<category>): '<token>'`) and route non-keyword parse-type-spec failures through these diagnostics with focused parser coverage.
  - Iteration 3 slice: replaced type-name punctuator token fallbacks with punctuator-specific messages for declarator-shape parse branches (`(` / `[` / `;`) and kept parse acceptance behavior unchanged.
  - Iteration 3 slice: expanded type-name punctuator diagnostics for missing-type association separators (`)` / `,` / `:`), reducing generic `Unsupported type name punctuator` fallbacks in malformed `_Generic` associations.
  - Iteration 3 slice: expanded type-name punctuator diagnostics for additional malformed `_Generic` association separators (`?` / `]` / `}`) and added focused parser regression coverage for each punctuation shape.
  - Iteration 3 slice: replaced remaining type-name token fallback diagnostics for malformed `_Generic` association starts by adding explicit non-punctuator and end-of-input messages (`Type name cannot start with <token-kind>...` / `Type name is missing before end of input`), plus focused parser regression coverage.
  - Iteration 3 slice: replaced declaration-context punctuator fallback diagnostics with punctuator-specific messages (`Declaration type cannot start with ...` / `Declaration type is missing before ...`) and added focused parser regression tests for `(`, `[`, and `;` malformed declaration starts.
  - Iteration 3 slice: added a dedicated declaration-context right-parenthesis diagnostic (`Declaration type is missing before ')'`) to reduce remaining `Unsupported declaration type punctuator` fallback usage, with focused parser regression coverage.
  - Iteration 3 slice: added a dedicated declaration-context `*` diagnostic (`Declaration type is missing before '*': pointer declarator requires a base type`) to reduce generic punctuator fallback usage for malformed pointer-style declaration starts, with focused parser regression coverage.
  - Iteration 3 slice: added a dedicated declaration-context `...` diagnostic (`Declaration type is missing before '...': expected a type specifier`) and parser regression coverage, reducing another `Unsupported declaration type punctuator` fallback path.
  - Iteration 3 slice: mapped `-` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '-'...` / `Type name cannot start with '-'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `/` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '/'...` / `Type name cannot start with '/'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `%` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '%'...` / `Type name cannot start with '%'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `%:` digraph punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '%:'...` / `Type name cannot start with '%:'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `%:%:` digraph punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '%:%:'...` / `Type name cannot start with '%:%:'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `*` punctuator fallback in type-name contexts to an explicit diagnostic (`Type name cannot start with '*': expected a type specifier`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `.` and `->` punctuator fallbacks in type-name contexts to explicit diagnostics (`Type name cannot start with '.': ...` / `Type name cannot start with '->': ...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `{` punctuator fallback in type-name contexts to an explicit missing-type diagnostic (`Type name is missing before '{'`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `!` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '!'...` / `Type name cannot start with '!'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `~` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '~'...` / `Type name cannot start with '~'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `&` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '&'...` / `Type name cannot start with '&'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `|` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '|'...` / `Type name cannot start with '|'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `^` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '^'...` / `Type name cannot start with '^'...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped `=` punctuator fallbacks in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '='...` / `Type name cannot start with '='...`) and added focused parser regression coverage.
  - Iteration 3 slice: mapped shift punctuator fallbacks (`<<` / `>>`) in declaration/type-name contexts to explicit diagnostics and added focused parser regression coverage.
  - Iteration 3 slice: mapped compound-assignment punctuator fallbacks (`+=`, `-=`, `*=`, `/=`, `%=` , `&=`, `|=`, `^=`, `<<=`, `>>=`) in declaration/type-name contexts to explicit diagnostics, and added focused parser regression coverage for representative `+=` and `<<=` cases.
  - Iteration 3 slice: expanded parser regression coverage for all remaining compound-assignment punctuator diagnostics in declaration and type-name contexts (`-=`, `*=`, `/=`, `%=` , `&=`, `|=`, `^=`, `>>=`), locking down every mapped token path.
  - Iteration 3 slice: mapped remaining declaration/type-name punctuator fallback diagnostics for preprocessor/digraph tokens (`#`, `##`, `<:`, `:>`, `<%`, `%>`) and added focused parser regression coverage to keep those paths out of generic unsupported-punctuator fallbacks.
  - Iteration 3 slice: added a curated clang-manifest regression case for `#` in declaration type-start position (`int f(#);`) with explicit parse-stage message/position expectations, so external fixture coverage now tracks the hash-specific diagnostic path too.
  - Iteration 3 slice: added a sibling curated clang-manifest regression case for `##` in declaration type-start position (`int f(##);`) with explicit parse-stage message/position expectations, completing hash-token declaration-start coverage in the external fixture suite.
  - Iteration 3 slice: added curated clang-manifest regression coverage for a type-name-start `##` diagnostic path via malformed `_Generic` association (`_Generic(x, ##: 1, default: 0)`), with explicit parse-stage message/position expectations.
  - Iteration 3 slice: added the paired curated clang-manifest regression case for type-name-start `#` in malformed `_Generic` association coverage (`_Generic(x, #: 1, default: 0)`), including explicit parse-stage message/position expectations.
  - Iteration 3 slice: added a curated clang-manifest regression case for the type-name-start `<:` digraph diagnostic path in malformed `_Generic` association coverage (`_Generic(x, <:: 1, default: 0)`), with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for the type-name-start `:>` digraph diagnostic path in malformed `_Generic` association coverage (`_Generic(x, :> : 1, default: 0)`), with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for the type-name-start `<%` digraph diagnostic path in malformed `_Generic` association coverage (`_Generic(x, <% : 1, default: 0)`), with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `%:` digraph coverage (`int f(%:);`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `%:%:` digraph coverage (`int f(%:%:);`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `<%` digraph coverage (`int f(<%);`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `:>` digraph coverage (`int f(:>);`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `<:` digraph coverage in function-parameter context (`int f(<:);`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `%>` digraph coverage in a non-parameter declaration context (`%> value;`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `:>` digraph coverage in a non-parameter declaration context (`:> value;`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `<:` digraph coverage in a non-parameter declaration context (`<: value;`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `<%` digraph coverage in a non-parameter declaration context (`<% value;`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `%:%:` digraph coverage in a non-parameter declaration context (`%:%: value;`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `%:` digraph coverage in a non-parameter declaration context (`%: value;`) with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `%:` digraph coverage in struct-member declaration context (`struct S { %: member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
  - Iteration 3 slice: added the paired curated clang-manifest regression case for declaration type-start `%:%:` digraph coverage in struct-member declaration context (`struct S { %:%: member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Remaining risk: full C11 pointer qualification rules still need structural pointer-level qualifier modeling (current `Type` qualifier representation is base-type-centric).
- Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `<:` digraph coverage in struct-member declaration context (`struct S { <: member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added the paired curated clang-manifest regression case for declaration type-start `<%` digraph coverage in struct-member declaration context (`struct S { <% member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `:>` digraph coverage in struct-member declaration context (`struct S { :> member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added curated clang-manifest regression coverage for hash-at-line-start member declarations (`struct S { # member; };`) as a preprocessor-stage failure (`Unknown preprocessor directive: #member`), with explicit stage/message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `##` coverage in struct-member declaration context (`struct S { ## member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `*` in struct-member declaration context (`struct S { * member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for declaration type-start `...` in struct-member declaration context (`struct S { ... member; };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for variadic declarator misuse (`int f(...);`) to lock down the parser diagnostic path `Expected parameter before ...` in the external clang fixture suite.
- Iteration 3 slice: added the sibling curated clang-manifest regression case for function-pointer variadic misuse (`int (*fp)(...);`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for block-scope non-pointer variadic declarator misuse (`int main(){int f(...);return 0;}`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Iteration 3 slice: added a curated clang-manifest regression case for variadic declarator misuse in `for`-init declaration context (`int main(){for (int f(...);;){}}`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Iteration 3 slice: added a curated clang-manifest regression case for function-pointer variadic declarator misuse in `for`-init declaration context (`int main(){for (int (*fp)(...);;){}}`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Iteration 3 slice: added a curated clang-manifest regression case for function-pointer variadic declarator misuse in struct-member declaration context (`struct S { int (*fp)(...); };`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Iteration 3 slice: added a curated clang-manifest regression case for non-pointer variadic declarator misuse in struct-member declaration context (`struct S { int f(...); };`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Iteration 3 slice: added a sibling curated clang-manifest regression case for non-pointer variadic declarator misuse in union-member declaration context (`union U { int f(...); };`) with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add a curated clang-manifest regression case for variadic declarator misuse in typedef declaration context (`typedef int f(...);`) to lock down the same parser diagnostic path in typedef scope.
- Iteration 3 slice: added a curated clang-manifest regression case for function-pointer variadic declarator misuse in union-member declaration context (`union U { int (*fp)(...); };`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Iteration 3 slice: added a curated clang-manifest regression case for function-pointer variadic declarator misuse in typedef declaration context (`typedef int (*fp)(...);`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add a curated clang-manifest regression case for variadic declarator misuse in typedef declaration context inside block scope (`int main(){ typedef int f(...); return 0; }`) to lock down this parser diagnostic path in nested typedef scope.
- Iteration 3 slice: added a curated clang-manifest regression case for variadic declarator misuse in block-scope typedef declaration context (`int main(){ typedef int f(...); return 0; }`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add the sibling curated clang-manifest regression case for function-pointer variadic declarator misuse in block-scope typedef context (`int main(){ typedef int (*fp)(...); return 0; }`) to lock down the same parser diagnostic path for nested typedef function pointers.
- Iteration 3 slice: added a curated clang-manifest regression case for function-pointer variadic declarator misuse in block-scope typedef context (`int main(){ typedef int (*fp)(...); return 0; }`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add a focused parser unit regression (non-clang fixture) for function-pointer variadic misuse in block-scope typedef context so this diagnostic path is covered in both local parser tests and external clang fixtures.
- Iteration 3 slice: added a focused parser unit regression for typedef variadic declarator misuse at file scope (`typedef int f(...);`) and asserted the exact diagnostic (`Expected parameter before ...`) so this path is covered outside the external clang fixture suite.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_variadic_typedef_requires_fixed_parameter_at_file_scope tests.test_parser.ParserTests.test_variadic_typedef_function_pointer_requires_fixed_parameter_in_block_scope` (pass); `.venv/bin/python -m unittest tests.test_parser -q` (pass).
- Next target: add the sibling focused parser unit regression for file-scope function-pointer typedef variadic misuse (`typedef int (*fp)(...);`) to mirror existing clang-fixture coverage in local parser tests.
- Iteration 3 slice: tightened local parser regression for block-scope variadic function-pointer misuse (`int main(){int (*fp)(...);return 0;}`) by asserting the exact diagnostic message (`Expected parameter before ...`) instead of only checking that parsing fails.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_variadic_function_pointer_requires_fixed_parameter tests.test_parser.ParserTests.test_variadic_typedef_function_pointer_requires_fixed_parameter_at_file_scope` (pass); `.venv/bin/python -m unittest tests.test_parser -q` (pass).
- Next target: add a focused parser unit regression for non-typedef file-scope variadic function declarator misuse (`int f(...);`) with exact diagnostic assertion to mirror the existing clang fixture and strengthen local diagnostic stability coverage.
- Iteration 3 slice: added a focused parser unit regression for function-pointer variadic misuse in struct-member declaration context (`struct S { int (*fp)(...); };`) and asserted the exact diagnostic (`Expected parameter before ...`) so this parser path is now covered in local unit tests, not only clang fixtures.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_variadic_function_pointer_requires_fixed_parameter_in_struct_member tests.test_parser -q` (pass).
- Next target: add the sibling focused parser unit regression for non-pointer variadic misuse in struct-member declaration context (`struct S { int f(...); };`) with the same exact diagnostic assertion.
- Iteration 3 slice: added a focused parser unit regression for non-pointer variadic declarator misuse in `for`-init declaration context (`int main(){for (int f(...);;){} }`) and asserted the exact diagnostic (`Expected parameter before ...`), mirroring existing external clang fixture coverage in local parser tests.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_variadic_function_requires_fixed_parameter_in_for_init_declaration tests.test_parser.ParserTests.test_variadic_function_pointer_requires_fixed_parameter_in_for_init_declaration` (pass); `.venv/bin/python -m unittest tests.test_parser -q` (pass).
- Next target: add a focused parser unit regression for non-pointer variadic declarator misuse in block-scope declaration context (`int main(){int f(...);return 0;}`) with exact diagnostic assertion to mirror external clang fixture coverage locally.
- Iteration 3 slice: added a curated clang-manifest regression case for variadic declarator misuse in `for`-init typedef declaration context (`int main(){for (typedef int f(...);;){} }`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add the sibling curated clang-manifest regression case for function-pointer variadic declarator misuse in `for`-init typedef declaration context (`int main(){for (typedef int (*fp)(...);;){} }`) to lock down the same parser diagnostic path for typedef function pointers in `for`-init declarations.
- Iteration 3 slice: added a curated clang-manifest regression case for function-pointer variadic declarator misuse in `for`-init typedef declaration context (`int main(){for (typedef int (*fp)(...);;){} }`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add a focused local parser unit regression for function-pointer variadic declarator misuse in `for`-init typedef declaration context so this diagnostic path is covered in both local parser tests and external clang fixtures.
- Iteration 3 slice: added a focused local parser unit regression for non-pointer variadic declarator misuse in block-scope declaration context (`int main(){int f(...);return 0;}`) and asserted the exact diagnostic (`Expected parameter before ...`) so this parser path is now locked down in local tests.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_variadic_function_requires_fixed_parameter_in_block_scope tests.test_parser -q` (pass).
- Next target: add a focused local parser unit regression for non-pointer variadic declarator misuse in union-member context (`union U { int f(...); };`) to keep local parser coverage aligned with existing clang fixture diagnostics.
- Iteration 3 slice: mapped remaining unary punctuator type-start fallbacks for `++` and `--` in declaration/type-name contexts to explicit diagnostics (`Declaration type is missing before '++'/'--'...` and `Type name cannot start with '++'/'--'...`), and added focused local parser regression coverage for all four paths.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_unsupported_declaration_type_punctuator_reports_increment_message tests.test_parser.ParserTests.test_unsupported_declaration_type_punctuator_reports_decrement_message tests.test_parser.ParserTests.test_unsupported_type_name_punctuator_reports_increment_message tests.test_parser.ParserTests.test_unsupported_type_name_punctuator_reports_decrement_message` (pass); `.venv/bin/python -m unittest tests.test_parser -q` (pass).
- Iteration 3 slice: added curated clang-manifest regression cases for declaration/type-name type-start `++` and `--` punctuator diagnostics (`int f(++);`, `int f(--);`, and malformed `_Generic` associations with `++`/`--`), with explicit parse-stage message/position expectations and fixture checksum tracking.
- Checks: `uvx tox -e clang_suite -- -q` (pass).
- Next target: add a focused local parser unit regression for non-pointer variadic declarator misuse in union-member context (`union U { int f(...); };`) to keep local parser coverage aligned with existing clang fixture diagnostics.
- Iteration 3 slice: mapped type-name punctuator fallback for `...` to an explicit diagnostic (`Type name cannot start with ...: expected a type specifier`), and added both a focused local parser regression and a curated clang-manifest fixture for malformed `_Generic` associations with checksum tracking.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_unsupported_type_name_punctuator_reports_ellipsis_message tests.test_parser -q` (pass); `uvx tox -e clang_suite -- -q` (pass).
- Next target: add the sibling declaration-context coverage for `...` in malformed declaration starts inside `_Static_assert`/type-name-adjacent parser paths to keep punctuator diagnostics consistent across declaration/type-name entry points.
- Iteration 3 slice: replaced the generic expression-start fallback (`Unexpected token`) for ellipsis with a dedicated parser diagnostic (`Expression cannot start with '...': expected an operand`) and added both a focused local parser regression and a curated clang-manifest fixture for block-scope `_Static_assert`-adjacent usage.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_expression_start_ellipsis_after_static_assert_reports_operand_diagnostic tests.test_parser -q` (pass); `.venv/bin/python -m unittest tests.test_clang_suite.ClangSuiteTests.test_clang_manifest_case_schema tests.test_clang_suite.ClangSuiteTests.test_clang_fixtures_match_manifest_checksums -q` (pass).
- Note: `uvx tox -e clang_suite -- -q` is currently blocked by an unrelated preprocessor runtime failure in the dirty workspace (`NameError: _format_date_macro` from `src/xcc/preprocessor.py`) before parser fixtures execute.
- Next target: add the sibling expression-entry diagnostics for other punctuation-only operand starts that still funnel through generic `Unexpected token` in `_parse_primary` (for example `]`/`}`) with focused parser regressions.
- Iteration 3 slice: fixed preprocessor translation-time macro support by defining `__DATE__`/`__TIME__` as concrete string macros at translation start, restoring runtime stability and macro-table visibility while keeping `__FILE__`/`__LINE__` as location-dependent dynamic macros.
- Checks: `.venv/bin/python -m unittest tests.test_preprocessor.PreprocessorTests.test_predefined_date_and_time_macros_use_translation_start_time tests.test_preprocessor -q` (pass).
- Next target: resume parser diagnostic hardening by adding focused `_parse_primary` regressions for punctuation-only operand starts (`]`/`}`) that still report generic `Unexpected token`.
- Iteration 3 slice: replaced `_parse_primary` generic `Unexpected token` fallbacks for punctuation-only expression starts `]` and `}` with explicit operand diagnostics (`Expression cannot start with ']': expected an operand` / `Expression cannot start with '}': expected an operand`) and added focused parser regression coverage in block-scope `_Static_assert`-adjacent contexts.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_expression_start_right_bracket_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_right_brace_reports_operand_diagnostic tests.test_parser -q` (pass).
- Next target: add sibling `_parse_primary` expression-start diagnostics for additional punctuation-only operands that still report generic `Unexpected token` (for example `)`), with focused parser regressions mirroring statement-adjacent entry points.
- Iteration 3 slice: replaced `_parse_primary` generic `Unexpected token` fallbacks for delimiter-led expression starts (`)`, `,`, `:`) and `}` with explicit operand diagnostics, and added focused parser regression coverage for statement-adjacent entry points.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_expression_start_right_paren_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_comma_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_colon_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_right_brace_reports_operand_diagnostic tests.test_parser -q` (pass).
- Next target: add sibling `_parse_primary` expression-start diagnostics for additional punctuation-only operands still using generic `Unexpected token` (for example `?`), with focused parser regressions for statement-adjacent entry points.
- Iteration 3 slice: replaced `_parse_primary` generic `Unexpected token` fallbacks for expression starts `?`, `;`, and `{` with explicit operand diagnostics (`Expression cannot start with '?'/';'/'{': expected an operand`), and added focused parser regressions that cover each entry path in expression-required contexts.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_expression_start_question_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_semicolon_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_left_brace_reports_operand_diagnostic tests.test_parser -q` (pass).
- Next target: extend `_parse_primary` punctuation-start operand diagnostics for remaining operator-only punctuators that still fall through to generic `Unexpected token` (for example `%>` digraph or `##`), with both focused local parser regressions and curated clang-manifest fixtures where parser-stage coverage is reachable.
- Iteration 3 slice: replaced `_parse_primary` generic `Unexpected token` fallbacks for hash/digraph punctuation-led expression starts (`##`, `%:`, `%:%:`, `<:`, `:>`, `<%`, `%>`) with explicit operand diagnostics (`Expression cannot start with '<token>': expected an operand`), keeping parser behavior unchanged while hardening message specificity.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_expression_start_token_paste_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_hash_digraph_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_hash_hash_digraph_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_right_brace_digraph_reports_operand_diagnostic` (pass); `.venv/bin/python -m unittest tests.test_parser -q` (pass).
- Next target: add focused local parser regressions for the newly-mapped `<:` / `:>` / `<%` digraph expression-start diagnostics to lock down all delimiter-digraph operand-entry paths explicitly.
- Iteration 3 slice: added focused local parser regressions for expression-start diagnostics on `<:`, `:>`, and `<%`, so all delimiter digraph operand-entry paths now assert exact `Expression cannot start with ...` messages in parser unit tests.
- Checks: `.venv/bin/python -m unittest tests.test_parser.ParserTests.test_expression_start_left_bracket_digraph_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_right_bracket_digraph_reports_operand_diagnostic tests.test_parser.ParserTests.test_expression_start_left_brace_digraph_reports_operand_diagnostic tests.test_parser -q` (pass).
- Next target: add curated clang-manifest fixtures for expression-start digraph operand diagnostics (`<:`, `:>`, `<%`, `%>`) in statement-adjacent contexts so external conformance coverage mirrors local parser-unit coverage.
