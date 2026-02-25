# TODO

This file tracks remaining work toward a production-ready C11 compiler. It includes both frontend and backend scope, but only the frontend section is expanded for now.

## 0. Milestone View

- [ ] M0: Complete C11 frontend conformance baseline.
- [ ] M1: Add minimal IR and code generation for macOS arm64.
- [ ] M2: Add Linux/ELF backend path (mold + glibc/musl).
- [ ] M3: Compile CPython core with no source modifications.
- [ ] M4: Harden diagnostics, compatibility, and performance.

## Sprint Mode (2026-02-25 -> 2026-03-10)

M4 remains the final target. This sprint does **not** redefine success; it accelerates the path to M4 by forcing strict prioritization and parallel closure.

### Sprint Rules (quality-preserving acceleration)

- [ ] Keep M4 as the final acceptance target (no scope downgrade).
- [ ] Every change is test-first: add/adjust failing test before behavior change.
- [ ] No merge without green scoped checks + no unrelated regressions.
- [ ] Daily failure-bucket triage from CPython/frontend fixture runs (preprocessor/parser/sema/diagnostics/backend).
- [ ] Prioritize blockers by impact-frequency, not by local convenience.
- [ ] Keep docs and TODO status updated in the same commit as code/tests.

### Two-Week Top Priorities (ordered)

- [ ] P0: Stabilize baseline quality gates in active dev env (`py311`, `lint`, `type`, `clang_suite`) and eliminate known environment/baseline red states.
- [ ] P1: Close remaining C11 preprocessor macro replacement/rescanning edge cases and directive-tail strictness gaps.
- [ ] P2: Complete parser coverage for remaining unsupported declarator/array-size/initializer grammar paths required by C11.
- [ ] P3: Remove remaining sema `Unsupported statement/expression` fallbacks by implementing required semantic branches.
- [ ] P4: Finish high-risk conversion/type-compatibility gaps (usual arithmetic conversions, pointer compatibility, assignment constraints).
- [ ] P5: Normalize and lock actionable diagnostics for all high-frequency rejection paths (with stable source context).
- [ ] P6: Expand curated clang fixtures + local regressions to cover all newly closed diagnostic/grammar paths.
- [ ] P7: Run recurring CPython-driven frontend trials and convert each failure bucket into reproducible tests before implementation.
- [ ] P8: Define and freeze M1 minimal IR/lowering contract so frontend outputs are backend-ready (without blocking M0 closure).

### Sprint Exit Criteria

- [ ] M0 risk ledger updated with no unknown-severity blockers.
- [ ] All sprint P0-P7 items either completed or explicitly deferred with owner + rationale.
- [ ] Continuous green runs for `tox -e py311`, `tox -e lint`, `tox -e type`, and `tox -e clang_suite` on sprint branch tip.
- [ ] CPython frontend trial report produced with categorized pass/fail trend and next blocking set.

## 1. Frontend (Expanded)

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

## Progress Log

- Progress entries were moved to `CHANGELOG.md` to keep this file focused on planning and prioritization.
- Add new implementation logs to `CHANGELOG.md` in the same commit as code/tests/docs updates.
