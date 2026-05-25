# SPEC

## §G GOAL
Python stdlib-only C11 compiler with target-driven codegen; default target `llvm`, future targets possible.

## §C CONSTRAINTS
- Runtime deps = Python standard library only.
- Host Python support: CPython 3.11+.
- `from __future__ import annotations` ⊥.
- GPL sources/tests ⊥.
- Target default = `llvm`; users need not pass `--target=llvm`.
- Target selection ! use `--target=<name>`; internal `--backend` mode flag ⊥.
- LLVM target object output ! via `/opt/homebrew/opt/llvm/bin/llc`.
- `CHANGELOG.md` records status changes.
- `LESSONS.md` records reusable bug lessons.
- Handoff ! run `uv run tox -e lint` & `uv run tox -e type`.
- Vibe coding allowed; unverified generated code ⊥ accepted.
- Behavior changes ! have smallest reproducer test before broad fix.
- Existing user changes ! preserved; unrelated refactor ⊥.
- Compiler pipeline special-cases for CPython paths/files/macros ⊥.
- CPython fixes ! generalize to C semantics, ABI, driver compatibility, or diagnostics.

## §I INTERFACES
- cmd: `xcc [--target=llvm] ...` → CC-style compile/link driver; target defaults to `llvm`.
- cmd: `xcc -c source.c -o source.o` → XCC frontend + LLVM IR + `llc` object.
- cmd: `xcc --target=llvm -c source.c -o source.o` → same explicit target form.
- cmd: `uv run python -m unittest discover -v` → unit regression suite.
- cmd: `uv run tox -e lint` → ruff check + format check.
- cmd: `uv run tox -e type` → `ty check src`.
- cmd: `CC="xcc" ./configure && make` in CPython tree → flagship integration gate.
- file: `src/xcc/preprocessor/` → C preprocessing.
- file: `src/xcc/lexer.py` → C tokenization.
- file: `src/xcc/parser/` → AST parse.
- file: `src/xcc/sema/` → type resolution, constants, layout, conversions.
- file: `src/xcc/codegen.py` → AST/sema unit → LLVM IR via libLLVM-C ctypes.
- file: `src/xcc/llvm_api.py` → raw libLLVM-C loading/signature boundary.
- file: `src/xcc/cc_driver.py` → compiler-driver arg handling, `llc`, clang link.
- file: `CHANGELOG.md` → current capability/status ledger.
- file: `LESSONS.md` → backprop lesson ledger.

## §V INVARIANTS
V1: ∀ runtime import path → stdlib only; dev deps ∉ runtime.
V2: ∀ Python src → CPython 3.11 syntax valid & `from __future__ import annotations` absent.
V3: ∀ borrowed external test/source → license Apache/BSD/MIT/PSF/permissive; GPL ⊥.
V4: ∀ bug fix → minimal failing C or CLI reproducer exists before behavior change.
V5: ∀ parser/sema/codegen semantic claim → clang or CPython behavior used as oracle when practical.
V6: ∀ ABI/layout change → tests cover `sizeof`, `alignof`, `offsetof`, field order, bit-field? relevant case.
V7: ∀ integer conversion/promotion change → tests cover signedness, width, constant folding, runtime IR? relevant case.
V8: ∀ initializer change → tests cover scalar, aggregate, nested aggregate, static storage? relevant case.
V9: ∀ control-flow codegen change → emitted IR passes `/opt/homebrew/opt/llvm/bin/llc` for reproducer.
V10: LLVM builder position ! read from `GetInsertBlock` after recursive emit; stale assumed block ⊥.
V11: LLVM null pointer checks ! handle `None` and `0`.
V12: `LLVMPositionBuilderAtEnd` on terminated block ⊥ unless caller proves insertion-before-terminator intended.
V13: `--backend` and `--no-backend-fallback` CLI options ⊥.
V14: `--target` accepted values ! explicit; unsupported target exits nonzero before compile.
V15: CPython-specific harnesses ⊥; compiler correctness comes from C semantics, clang oracle, unit reproducers, and real build.
V16: Compiler code ! never branch on CPython path/file/project identity.
V17: Integration gates ! use real build commands or project-agnostic replay of captured compile commands; curated project allowlists ⊥ gate.
V18: ∀ diagnostics test → message/location deterministic.
V19: ∀ `target=llvm` object path → `llc` command includes explicit optimization/filetype args expected by driver tests.
V20: Handoff after code edit ! `uv run tox -e lint` & `uv run tox -e type` pass or failure documented.
V21: Broad CPython build run ! delete stale `.o` first when object cache can mask regression.
V22: Vibe-coded patch accepted only after reproducer, local oracle/gate, and lesson/changelog update when behavior/status changes.

## §T TASKS
id|status|task|cites
T1|x|scaffold stdlib-only Python package + `xcc` console script|V1,I.cmd
T2|x|implement frontend pipeline preprocessor→lexer→parser→sema|I.file
T3|x|implement LLVM IR backend through libLLVM-C + `llc`|V9,I.file
T4|x|replace backend modes with target selection defaulting to `llvm`|V13,V14,I.cmd
T5|x|add unit suites for lexer/parser/sema/frontend/codegen/driver|V4,V18,I.cmd
T6|x|delete CPython-specific trial harness and tests|V15,V16,I.file
T7|x|record current CPython frontend/backend status in `CHANGELOG.md`|I.file
T8|x|record CPython build-loop lessons in `LESSONS.md`|I.file
T9|.|add project-agnostic real-build capture/replay design|V16,V17,I.cmd
T10|.|add project-agnostic compile-command replay harness from real build logs|V16,V17,I.cmd
T11|.|add clang-oracle helpers for layout/conversion/codegen regression tests|V5,V6,V7
T12|.|add generic single-file regression workflow docs/examples using minimized C + clang oracle|V4,V5,V9
T13|.|expand ABI/layout tests for structs, unions, bit-fields, anonymous records|V6
T14|.|expand initializer tests for nested aggregate/static-local/global cases|V8
T15|.|expand control-flow IR tests around ternary/logical/switch/goto/labels|V9,V10,V12
T16|.|use real-build integration gate before large changes|V15,V17,V22
T17|.|turn CPython-discovered failures into generic minimized C regression tests|V4,V5,V15
T18|.|verify full target `CC="xcc" ./configure && make` after high-risk codegen/sema changes|§G,V21

## §B BUGS
id|date|cause|fix
