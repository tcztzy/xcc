# AOT Python Strong Self-Hosting Implementation Plan

Status: proposed 2026-07-11; implementation requires user confirmation.

## Objective

Build a strong bootstrap chain:

```text
Stage 0 (CPython-hosted xcc.aot)
  -> Stage 1 (native xcc-aot)
  -> Stage 2 (native xcc-aot built from repository .py by Stage 1)
  -> Stage 3 (native xcc-aot built from the same .py by Stage 2)
```

Stage 1 and Stage 2 must parse source with the project-owned Python subset
frontend, not CPython `ast.parse`; neither may execute Python or depend on
libpython, Python C API symbols, or pre-generated AST/IR.

This plan implements `specs/aot-python.md` and the revised architecture in
`docs/superpowers/specs/2026-06-26-aot-python-design.md`. The current-state
evidence and source-change ledger are in
`docs/superpowers/specs/2026-07-11-aot-python-strong-bootstrap-audit.md`.

Native C compilation and CPython `configure && make` are deferred to Milestone
9. They remain important integration gates but do not define self-hosting.

## Execution Rules

1. Do not delete or roll back the current worktree merely to simplify the plan.
2. Before broad implementation, split current work into logical, bisectable
   commits. Never stage unrelated `docs/codex-for-oss-application.md` changes.
3. For every accepted Python construct, fix binder/lowerer/runtime semantics;
   do not rewrite non-AOT compiler source to avoid it.
4. Any non-`src/xcc/aot` AOT-driven edit requires a ledger entry, subset
   decision, CPython oracle, and native oracle.
5. Add a focused failing semantic test before each behavior change. Source-text
   shape assertions may supplement but never replace behavior tests.
6. Keep Stage outputs and generated probes under `build/aot/`; do not commit
   them as required bootstrap inputs.
7. Do not resume CPython configure blocker chasing before Milestone 8 passes.
8. Each milestone lands as one or more coherent commits with its own gate.

## Planned File Boundaries

New AOT-owned files:

- `src/xcc/aot/py_ast.py`
- `src/xcc/aot/py_lexer.py`
- `src/xcc/aot/py_parser.py`
- `src/xcc/aot/cpython_ast_adapter.py`
- `src/xcc/aot/cli.py`
- `src/xcc/aot/__main__.py`
- `src/xcc/aot/status.py` if the status/error model does not fit cleanly in IR
- `scripts/aot_bootstrap_gate.py`
- `scripts/normalize_aot_llvm.py`
- `scripts/aot_exec_audit.c` or equivalent platform audit helper
- focused tests named by layer: `test_aot_py_lexer.py`,
  `test_aot_py_parser.py`, `test_aot_status.py`, and bootstrap gate tests

Existing AOT files remain responsible for binding, IR, lowering, LLVM text,
runtime, native tool execution, and bootstrap orchestration. Existing C
compiler files are not the native AOT CLI implementation.

## Estimate Summary

Estimates are single-senior-engineer working days including focused tests and
review, but excluding external LLVM/toolchain defects. Parser and runtime work
have roughly +/-50% uncertainty until the source contract is frozen.

| Milestone | Estimate |
|---|---:|
| 1. Freeze Stage 0 and split worktree | 3-5 days |
| 2. Source contract, owned AST, native CLI contract | 3-5 days |
| 3. Project-owned Python subset lexer/parser | 12-20 days |
| 4. Exception/status ABI and runtime semantics | 10-18 days |
| 5. Make `xcc.aot` native-reachable | 7-12 days |
| 6. Stage 0 builds Stage 1 | 3-6 days |
| 7. Stage 1 builds Stage 2 without Python | 7-14 days |
| 8. Stage 2 builds stable Stage 3 | 4-8 days |
| 9. Final Python/C/CPython gates | 4-12 days |
| Total | 53-100 days |

## Milestone 1: Freeze Stage 0 and Split the Worktree

**Goal:** Preserve the current hosted AOT capability while converting the
58-file, `+17039/-2283` worktree into reviewable and bisectable commits.

**Work:**

1. Capture the exact baseline commands/results for hosted AOT tests, native C
   smoke, and the V367 atomic test. Record known failures without fixing them.
2. Produce a hunk-level inventory for all 32 modified non-AOT source files.
3. Separate commits in this order:
   - strong-bootstrap specs/design/audit/plan;
   - hosted subset checker and binder;
   - AOT IR/lowerer changes;
   - LLVM emitter/runtime changes;
   - native build/tool harness;
   - native C compiler integration helpers;
   - one commit per independently proven C semantic fix;
   - quarantined source-shape workarounds, each explicitly labeled.
4. Add a checked source-change ledger. Every row links commit, source hunk,
   subset decision, CPython oracle, and native oracle/missing gate.
   Milestone 1 records this in
   `docs/superpowers/specs/2026-07-11-aot-python-source-change-ledger.md`.
5. Establish a stable Stage 0 tag or branch point after all selected tests pass.

**Acceptance commands:**

```bash
git diff --check
git status --short
git log --oneline --decorate --reverse 182d9c7..HEAD
uv run python -m unittest \
  tests.test_aot \
  tests.test_aot_ir \
  tests.test_aot_llvm \
  tests.test_aot_native \
  tests.test_aot_bootstrap \
  tests.test_aot_milestone6 \
  -v
uv run tox -e lint
uv run tox -e type
```

Expected: each commit is independently testable; unrelated files are absent;
the ledger has no unclassified non-AOT hunk. Known V367/V368 failures may be
recorded in a dedicated quarantine commit but cannot be reported as passing
general exception/runtime semantics.

**Exit evidence:** Stage 0 baseline tag/commit, source-change ledger, and a
documented test matrix.

## Milestone 2: Freeze the Source Contract, Owned AST, and AOT CLI

**Status:** completed 2026-07-11. This completes the contract and Stage 0
adapter/native CLI shell only; lexer/parser, native compiler reachability, and
Stage 1 remain later milestones.

**Goal:** Define one source contract and one compiler CLI shared by hosted and
native execution.

**Work:**

1. Enumerate the exact grammar and runtime operations reachable from the future
   AOT CLI, lexer/parser, binder, lowerer, IR, emitter, and tool runner.
2. Add `py_ast.py` node types with deterministic spans and no CPython AST
   inheritance/dependency.
3. Add `cpython_ast_adapter.py`; all existing binder/lowerer entry points first
   migrate to project-owned AST.
4. Define CLI:

```text
python -m xcc.aot build ...
xcc-aot build ...
```

5. Add source manifest, dependency order, cache policy, parser selection, LLVM
   output, normalized IR output, and tool path options.
6. Hosted `--parser=cpython` and `--parser=subset` produce the same downstream
   AST interface. Native CLI accepts only `--parser=subset`.

**Acceptance commands:**

```bash
uv run python -m unittest \
  tests.test_aot_py_ast \
  tests.test_aot_cli \
  tests.test_aot_source_contract \
  -v
uv run python -m xcc.aot --help
uv run python -m xcc.aot build --help
uv run python -m xcc.aot build \
  --parser=cpython \
  --source-root src/xcc \
  --entry xcc.aot.cli:main \
  --emit-llvm build/aot/contract/hosted.ll \
  --source-manifest build/aot/contract/hosted.sources \
  --output build/aot/contract/hosted-xcc-aot
```

Expected: binder/lowerer public APIs no longer require CPython AST node types;
the CLI contract is deterministic; no source marker/decorator exists.

## Milestone 3: Implement the Project-Owned Python Subset Lexer/Parser

**Goal:** Parse every module in the active strong-bootstrap source set without
`ast.parse`.

**Work:**

1. Implement indentation, newlines, identifiers, keywords, literals,
   punctuation, comments, and source spans in `py_lexer.py`.
2. Implement module/import, class/function, annotations, statements,
   expressions, comprehensions admitted by the contract, and deterministic
   diagnostics in `py_parser.py`.
3. Keep the parser hand-written and subset-compatible; no generated artifact is
   required at runtime.
4. Build an AST normalizer and compare the project parser with
   `ast.parse -> cpython_ast_adapter` for all accepted fixtures.
5. Run the oracle over every active repository module. Add rejection fixtures
   for every excluded syntax category.
6. Make `ast.parse` imports unreachable whenever `--parser=subset` is selected.

**Acceptance commands:**

```bash
uv run python -m unittest \
  tests.test_aot_py_lexer \
  tests.test_aot_py_parser \
  tests.test_aot_parser_oracle \
  -v
uv run python -m xcc.aot parser-oracle \
  --source-root src/xcc \
  --entry xcc.aot.cli:main
uv run python -m xcc.aot build \
  --parser=subset \
  --no-cache \
  --source-root src/xcc \
  --entry xcc.aot.cli:main \
  --emit-normalized-ir build/aot/parser/subset.ir \
  --output build/aot/parser/subset-xcc-aot
rg -n 'ast\.parse|CPython AST' build/aot/parser/subset.reachability
```

Expected: parser oracle has zero accepted-source differences; rejection
diagnostics are stable; the subset build reachability report has no hosted AST
adapter or `ast.parse` call.

## Milestone 4: Implement Exception/Status ABI and Runtime Semantics

**Goal:** Replace default-return and process-exit exception lowering with an
explicit, compositional ABI; correctly implement every supported runtime shape
needed by the AOT compiler.

**Work:**

1. Add fallibility analysis and internal ABI:

```text
status fn(args..., result_out, error_out)
```

2. Add typed error records, source spans, status branches, handler dispatch,
   rethrow/propagation, and supported `finally` behavior.
3. Convert only the outer native CLI uncaught error to stderr and process exit.
4. Remove general `IrRaise -> exit(2)` behavior after status tests pass.
5. Implement correct semantics for supported `for`/`break`/`continue`, tuple
   iteration/comparison, dict lookup/membership/mutation, negative indexing,
   constructors, strings/bytes, and paths.
6. Add CPython/native behavior oracles before removing any source workaround.
7. Start retiring non-AOT source-shape workarounds one logical commit at a time;
   do not combine retirement with unrelated semantics.

**Acceptance commands:**

```bash
uv run python -m unittest \
  tests.test_aot_status \
  tests.test_aot_runtime_oracle \
  tests.test_aot_ir \
  tests.test_aot_llvm \
  -v
uv run python -m unittest \
  tests.test_aot_runtime_oracle.AotRuntimeOracleTests.test_for_break_continue \
  tests.test_aot_runtime_oracle.AotRuntimeOracleTests.test_tuple_value_semantics \
  tests.test_aot_runtime_oracle.AotRuntimeOracleTests.test_dict_lookup_membership \
  tests.test_aot_runtime_oracle.AotRuntimeOracleTests.test_negative_index \
  tests.test_aot_runtime_oracle.AotRuntimeOracleTests.test_try_except_cross_call \
  -v
/opt/homebrew/opt/llvm/bin/llc \
  -filetype=obj \
  build/aot/status/status-oracle.ll \
  -o build/aot/status/status-oracle.o
```

Expected: a caught error does not exit; an uncaught CLI error exits nonzero;
fallible calls cannot continue on a type-default success path; runtime fixtures
match CPython behavior.

## Milestone 5: Make `xcc.aot` Native-Reachable

**Goal:** Change the native root from the C compiler smoke driver to the actual
AOT compiler CLI and prove the complete compile pipeline is emitted.

**Work:**

1. Root bootstrap at `xcc.aot.cli:main`.
2. Include source loading, module resolution, subset lexer/parser, binder,
   lowerer, IR model/validator, LLVM emitter, runtime, and tool execution.
3. Remove fixed entry fixtures and function-name special emitters from the
   acceptance path. Temporary special leaves may remain outside the gate with
   explicit diagnostics.
4. Add a native reachability manifest with reason edges from CLI to every
   included function/type.
5. Add negative checks for `xcc.cc_driver._aot_compile_smoke_source_to_object`
   as the root and for hosted AST adapter symbols.
6. Compile a small independent `.py` program using the generated native AOT
   compiler before attempting self-compilation.

**Acceptance commands:**

```bash
uv run python -m unittest \
  tests.test_aot_reachability \
  tests.test_aot_native_cli \
  -v
uv run python -m xcc.aot build \
  --parser=cpython \
  --source-root src/xcc \
  --entry xcc.aot.cli:main \
  --emit-llvm build/aot/reachability/xcc-aot.ll \
  --output build/aot/reachability/xcc-aot
rg -n 'xcc\.aot\.(py_lexer|py_parser|binder|lower|llvm_text|cli)' \
  build/aot/reachability/xcc-aot.reachability
! rg -n 'ast\.parse|cpython_ast_adapter|_aot_compile_smoke_source_to_object' \
  build/aot/reachability/xcc-aot.reachability
nm build/aot/reachability/xcc-aot | \
  rg 'xcc\.aot\.(py_lexer|py_parser|binder|lower|llvm_text|cli)'
```

Expected: every required AOT layer is reachable and present; no hosted parser
or C-smoke root is required.

## Milestone 6: Stage 0 Builds Stage 1

**Goal:** Freeze the hosted bootstrap and produce the first native AOT compiler.

**Work:**

1. Build Stage 1 from a clean generated-output directory with the hosted
   CPython AST adapter.
2. Emit source manifest, reachability manifest, LLVM, normalized IR, tool log,
   and executable.
3. Verify Stage 1 starts without Python, reports native mode, rejects
   `--parser=cpython`, and compiles a subset smoke program from source.
4. Audit dynamic libraries and undefined symbols.

**Acceptance commands:**

```bash
rm -rf build/aot/stage1
uv run python -m xcc.aot build \
  --parser=cpython \
  --no-cache \
  --source-root src/xcc \
  --entry xcc.aot.cli:main \
  --emit-llvm build/aot/stage1/xcc-aot.ll \
  --emit-normalized-ir build/aot/stage1/xcc-aot.norm.ll \
  --source-manifest build/aot/stage1/sources.json \
  --tool-log build/aot/stage1/tools.log \
  --output build/aot/stage1/xcc-aot
build/aot/stage1/xcc-aot --version
! build/aot/stage1/xcc-aot build --parser=cpython --help
otool -L build/aot/stage1/xcc-aot | tee build/aot/stage1/otool.txt
nm -u build/aot/stage1/xcc-aot | tee build/aot/stage1/undefined.txt
rg '^command=' build/aot/stage1/tools.log
! rg -i '(^|/)(python|python3)([0-9.]*)?($|[[:space:]])' \
  build/aot/stage1/tools.log
! rg -i 'libpython|Python\.framework|_Py[A-Za-z_]|Py[A-Z][A-Za-z_]+' \
  build/aot/stage1/otool.txt build/aot/stage1/undefined.txt
```

Expected: Stage 1 exists, has no Python dependency, exposes the native AOT CLI,
and can compile a source fixture through the subset parser.

## Milestone 7: Stage 1 Builds Stage 2 Without Python

**Goal:** Perform the first true native source bootstrap.

**Work:**

1. Build the exec/open audit shim without Python.
2. Delete Stage 2 caches and generated AST/IR.
3. Invoke Stage 1 directly with `--parser=subset --no-cache` and an allowlisted
   PATH containing only `llc`, assembler/linker, and basic shell tools needed by
   the gate.
4. Record every process exec and source open. Require repository `.py` reads and
   reject Python executables.
5. Verify Stage 2 dependencies/symbols and run compiler behavior fixtures.

**Acceptance commands:**

```bash
cc -dynamiclib scripts/aot_exec_audit.c -o build/aot/audit/libaot_exec_audit.dylib
rm -rf build/aot/stage2
mkdir -p build/aot/stage2
env \
  DYLD_INSERT_LIBRARIES="$PWD/build/aot/audit/libaot_exec_audit.dylib" \
  XCC_AOT_AUDIT_LOG="$PWD/build/aot/stage2/exec-open.log" \
  XCC_LLC=/opt/homebrew/opt/llvm/bin/llc \
  build/aot/stage1/xcc-aot build \
    --parser=subset \
    --no-cache \
    --source-root src/xcc \
    --entry xcc.aot.cli:main \
    --emit-llvm build/aot/stage2/xcc-aot.ll \
    --emit-normalized-ir build/aot/stage2/xcc-aot.norm.ll \
    --source-manifest build/aot/stage2/sources.json \
    --output build/aot/stage2/xcc-aot
! rg -i '(^|/)(python|python3)([0-9.]*)?($| )|libpython' \
  build/aot/stage2/exec-open.log
rg 'OPEN .*src/xcc/.*\.py' build/aot/stage2/exec-open.log
otool -L build/aot/stage2/xcc-aot > build/aot/stage2/otool.txt
nm -u build/aot/stage2/xcc-aot > build/aot/stage2/undefined.txt
! rg -i 'libpython|Python\.framework|_Py[A-Za-z_]|Py[A-Z][A-Za-z_]+' \
  build/aot/stage2/otool.txt build/aot/stage2/undefined.txt
```

Expected: Stage 1 actually reads `.py`, launches no Python process, and creates
a runnable Stage 2 from source alone.

Linux uses the equivalent `LD_PRELOAD` audit helper and `ldd` checks. If platform
security blocks interposition, use an approved syscall tracer and preserve the
raw trace as evidence.

## Milestone 8: Stage 2 Builds Stage 3 and Stabilizes

**Goal:** Close and verify the native bootstrap loop.

**Work:**

1. Repeat the cache-free audited native build with Stage 2 to produce Stage 3.
2. Normalize Stage 2/3 LLVM with a documented normalizer.
3. Compare source manifests, normalized IR, exported symbols, and behavior
   fixtures.
4. Investigate every difference. Add only semantic-preserving normalization;
   never mask differing function bodies, constants, layouts, or call targets.
5. Repeat the Stage 2->3 build twice to verify determinism.

**Acceptance commands:**

```bash
rm -rf build/aot/stage3
env \
  DYLD_INSERT_LIBRARIES="$PWD/build/aot/audit/libaot_exec_audit.dylib" \
  XCC_AOT_AUDIT_LOG="$PWD/build/aot/stage3/exec-open.log" \
  XCC_LLC=/opt/homebrew/opt/llvm/bin/llc \
  build/aot/stage2/xcc-aot build \
    --parser=subset \
    --no-cache \
    --source-root src/xcc \
    --entry xcc.aot.cli:main \
    --emit-llvm build/aot/stage3/xcc-aot.ll \
    --emit-normalized-ir build/aot/stage3/xcc-aot.norm.ll \
    --source-manifest build/aot/stage3/sources.json \
    --output build/aot/stage3/xcc-aot
! rg -i '(^|/)(python|python3)([0-9.]*)?($| )|libpython' \
  build/aot/stage3/exec-open.log
rg 'OPEN .*src/xcc/.*\.py' build/aot/stage3/exec-open.log
cmp build/aot/stage2/xcc-aot.norm.ll build/aot/stage3/xcc-aot.norm.ll
nm -gU build/aot/stage2/xcc-aot | sort > build/aot/stage2/symbols.txt
nm -gU build/aot/stage3/xcc-aot | sort > build/aot/stage3/symbols.txt
cmp build/aot/stage2/symbols.txt build/aot/stage3/symbols.txt
uv run python scripts/aot_bootstrap_gate.py compare-behavior \
  build/aot/stage2/xcc-aot build/aot/stage3/xcc-aot
```

The final Python comparison command runs only after native Stage 3 exists; it is
not in the Stage 2->3 build process tree.

Expected: normalized IR and exported symbols match, behavior fixtures are
equivalent, and audited Stage 2->3 contains no Python execution.

## Milestone 9: Final Compatibility and Integration Gates

**Goal:** Prove strong self-hosting did not regress normal Python behavior or
the native C compiler integration path.

**Work:**

1. Run all focused AOT and runtime oracle tests.
2. Run the complete Python test suite under CPython 3.11+.
3. Run lint and type gates.
4. Build/run the native C compiler smoke from the accepted source.
5. Only now resume and finish native `CC="xcc"` CPython `configure && make`.
6. Re-run Stage 1->2 and Stage 2->3 after any shared source change caused by
   final integration work.
7. Record exact stage hashes, manifests, dependency audits, process traces,
   normalized IR checksums, and final gate results in `CHANGELOG.md`.

**Acceptance commands:**

```bash
uv run python -m unittest discover -v
uv run tox -e py311
uv run tox -e lint
uv run tox -e type
git diff --check

uv run python -m unittest tests.test_aot_bootstrap -v
build/aot/stage2/xcc-aot --version

UV_CACHE_DIR=/private/tmp/uv-cache-xcc uv run python \
  scripts/validate_cpython_build.py \
  --cpython ../cpython \
  --build-dir build/cpython-native-aot \
  --clean \
  --native-aot-cc build/aot/xcc \
  --jobs 1 \
  --timeout 900
```

Native-AOT-backed integration remains serial until the runtime has verified
allocation lifetimes and a bounded out-of-memory path. Parallel native compiler
processes are not an accepted Milestone 9 gate while that work is incomplete.

Also repeat the direct audited Stage 1->2 and Stage 2->3 commands from
Milestones 7 and 8 after the final source commit.

Expected: all strong-bootstrap evidence remains valid; project imports/runs on
CPython 3.11+; no new syntax or marker decorator exists; Python, lint, type,
native C smoke, and CPython build gates all pass.

## Completion Checklist

- [ ] Worktree split into bisectable logical commits.
- [ ] Every non-AOT AOT-driven hunk has ledger and two-sided oracle evidence.
- [x] Project-owned AST exists and binder/lowerer no longer require CPython AST.
- [ ] Project-owned subset lexer/parser matches the Stage 0 oracle.
- [ ] Explicit status/result/error ABI implements supported handlers.
- [ ] Native AOT CLI and all compiler layers are reachable.
- [ ] Stage 0 builds Stage 1.
- [ ] Stage 1 reads `.py` and builds Stage 2 with no Python execution/dependency.
- [ ] Stage 2 reads `.py` and builds Stage 3 with no Python execution/dependency.
- [ ] Stage 2/3 normalized IR, exported symbols, and behavior are equivalent.
- [ ] CPython 3.11+ project behavior remains valid.
- [ ] No custom syntax, marker decorator, pragma, or comment directive exists.
- [ ] Full tests, lint, type, native C smoke, and CPython build gate pass.

Do not mark the AOT goal complete until every item has direct current-state
evidence. Passing all-source admission or compiling C natively is insufficient.
