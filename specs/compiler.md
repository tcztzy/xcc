# XCC C Compiler Spec

Canonical spec for the C compiler track. Root `SPEC.md` is only an index. This
file owns the shared C frontend, semantic model, compiler-wide constraints, and
target-neutral validation gates. Target selection belongs to `specs/driver.md`;
each concrete target owns its ABI/backend/assembler/linker contract in its own
`specs/target-<name>.md` file.

## §G GOAL
Python stdlib-only C11 compiler that accepts real C translation units, exposes a
CC-style driver, and validates shared frontend/semantic correctness without
owning concrete target behavior.

## §C CONSTRAINTS
- Runtime deps = Python standard library only.
- Host Python support: CPython 3.11+.
- `from __future__ import annotations` ⊥.
- GPL sources/tests ⊥.
- Target-selection/default rules live outside this spec in `specs/driver.md`.
- Concrete target ABI, backend, assembler, and linker rules live outside this
  spec in one `specs/target-<name>.md` file per target.
- `CHANGELOG.md` records status changes.
- `LESSONS.md` records reusable bug lessons.
- Handoff ! run `uv run tox -e lint` & `uv run tox -e type`.
- Vibe coding allowed; unverified generated code ⊥ accepted.
- Behavior changes ! have smallest reproducer test before broad fix.
- Existing user changes ! preserved; unrelated refactor ⊥.
- Compiler pipeline special-cases for CPython paths/files/macros ⊥.
- CPython fixes ! generalize to C semantics, frontend behavior, diagnostics, or
  the owning driver/target spec.

## §I INTERFACES
- cmd: `xcc ...` → CC-style compile/link driver; this spec owns shared
  frontend behavior only.
- cmd: `uv run python -m unittest discover -v` → unit regression suite.
- cmd: `uv run tox -e lint` → ruff check + format check.
- cmd: `uv run tox -e type` → `ty check src`.
- file: `src/xcc/preprocessor/` → C preprocessing.
- file: `src/xcc/lexer.py` → C tokenization.
- file: `src/xcc/parser/` → AST parse.
- file: `src/xcc/sema/` → type resolution, constants, layout, conversions.
- file: `CHANGELOG.md` → current capability/status ledger.
- file: `LESSONS.md` → backprop lesson ledger.
- spec: `specs/driver.md` → target-selection/default and cross-target driver
  gates.
- spec: `specs/target-<name>.md` → concrete target ABI/backend/assembler/linker
  gates, one file per target.

## §V INVARIANTS
V1: ∀ runtime import path → stdlib only; dev deps ∉ runtime.
V2: ∀ Python src → CPython 3.11 syntax valid & `from __future__ import annotations` absent.
V3: ∀ borrowed external test/source → license Apache/BSD/MIT/PSF/permissive; GPL ⊥.
V4: ∀ bug fix → minimal failing C or CLI reproducer exists before behavior change.
V5: ∀ parser/sema/codegen semantic claim → clang or CPython behavior used as oracle when practical.
V6: ∀ shared type-layout change → tests cover `sizeof`, `alignof`, `offsetof`, field order, bit-field? relevant case; concrete ABI rules belong to target specs.
V7: ∀ integer conversion/promotion change → tests cover signedness, width, constant folding, runtime IR? relevant case.
V8: ∀ initializer change → tests cover scalar, aggregate, nested aggregate, static storage? relevant case.
V15: CPython-specific harnesses ⊥; compiler correctness comes from C semantics, clang oracle, unit reproducers, and real build.
V16: Compiler code ! never branch on CPython path/file/project identity.
V17: Integration gates ! use real build commands or project-agnostic replay of captured compile commands; curated project allowlists ⊥ gate.
V18: ∀ diagnostics test → message/location deterministic.
V20: Handoff after code edit ! `uv run tox -e lint` & `uv run tox -e type` pass or failure documented.
V22: Vibe-coded patch accepted only after reproducer, local oracle/gate, and lesson/changelog update when behavior/status changes.
V23: GNU `void` return expression ! analyze operand + emit side effects before `ret void`; c11 keeps reject.
V24: Multi-line macro args ! collect through block comments and inactive conditional-directive lines; inactive branch directives do not abort expansion.
V25: Incomplete array init length ! largest initialized designator/range index + 1, not initializer item count; file/block sema and codegen agree.

## §T TASKS
id|status|task|cites
T1|x|scaffold stdlib-only Python package + `xcc` console script|V1,I.cmd
T2|x|implement frontend pipeline preprocessor→lexer→parser→sema|I.file
T5|x|add unit suites for lexer/parser/sema/frontend/codegen/driver|V4,V18,I.cmd
T6|x|delete CPython-specific trial harness and tests|V15,V16,I.file
T7|x|record current CPython frontend/backend status in `CHANGELOG.md`|I.file
T8|x|record CPython build-loop lessons in `LESSONS.md`|I.file
T9|.|add project-agnostic real-build capture/replay design|V16,V17,I.cmd
T10|.|add project-agnostic compile-command replay harness from real build logs|V16,V17,I.cmd
T11|.|add clang-oracle helpers for layout/conversion/codegen regression tests|V5,V6,V7
T12|.|add generic single-file regression workflow docs/examples using minimized C + clang oracle|V4,V5
T13|.|expand shared type-layout tests for structs, unions, bit-fields, anonymous records|V6
T14|.|expand initializer tests for nested aggregate/static-local/global cases|V8
T15|.|expand control-flow regression tests around ternary/logical/switch/goto/labels|V4,V5
T16|.|use real-build integration gate before large changes|V15,V17,V22
T17|.|turn CPython-discovered failures into generic minimized C regression tests|V4,V5,V15

## §B BUGS
id|date|cause|fix
B1|2026-05-26|GNU `void return expr;` skipped operand sema/codegen and lost call typemap|V23
B2|2026-05-26|macro arg collector stopped at block comments/inactive directives inside invocation|V24
B3|2026-05-26|sparse designated incomplete array used item count, truncating CPython function offset table|V25
