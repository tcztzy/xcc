# AOT Python Strong Bootstrap Gap Audit

Date: 2026-07-11

Baseline: `HEAD=182d9c7` on `codex/test-gate-hardening`, plus the current dirty
worktree. This audit preserves the worktree and classifies it; it does not
authorize deletion, rollback, or further CPython configure blocker work.

## Executive Conclusion

The repository currently has a Python-hosted AOT pipeline that can emit a
native C compiler executable. It does not yet have a strong self-hosting AOT
compiler.

The distinction is concrete:

```text
Current
  CPython + ast.parse + xcc.aot binder/lowerer/emitter
    -> build/aot/xcc (native C compiler)
    -> reads C source -> emits C-target LLVM/object

Required
  Stage 0 (CPython-hosted xcc.aot)
    -> Stage 1 (native xcc-aot)
    -> reads repository .py source with project-owned Python subset parser
    -> Stage 2 (native xcc-aot)
    -> reads the same .py source -> Stage 3 (native xcc-aot)
```

Compiling C without libpython is useful, but it proves only the native C
compiler integration path. It does not prove that native code can parse,
bind, lower, and emit the Python implementation of `xcc.aot`.

## Authoritative Evidence

| Claim | Current evidence | Audit result |
|---|---|---|
| Native binary has no libpython dependency | `otool -L build/aot/xcc` lists `libLLVM.dylib` and `libSystem.B.dylib` only | Proven for the current C compiler artifact |
| Native binary contains AOT compiler entry | `nm` and `build/aot/xcc.ll` contain `xcc.cc_driver._aot_compile_*`; `define ... @xcc.aot.*` count is zero | Contradicted |
| Native binary reads Python source to rebuild itself | Native entry is `_aot_compile_smoke_source_to_object(argc, argv)` and accepts C/object driver shapes | Contradicted |
| AOT frontend is independent of CPython AST | `module.py`, `binder.py`, `native.py`, and `slice.py` import `ast`; several call `ast.parse` | Contradicted |
| All source is native compile-reachable | admission runs hosted `analyze_path()` over 58 files; emitted native graph contains no `xcc.aot` definitions | Contradicted |
| Current tree is small/bisectable | 58 tracked files, `+17039/-2283`; two untracked docs | Contradicted |
| Stage 1 builds Stage 2 | No native Python AOT CLI or Stage 2 output exists | Missing |
| Stage 2 builds Stage 3 and stabilizes | No Stage 2/3 build exists | Missing |

## Current Worktree Size

Tracked diff against `HEAD`:

| Bucket | Files | Added | Deleted | Notes |
|---|---:|---:|---:|---|
| AOT implementation/tests/docs | 17 | 13,166 | 854 | Main reusable investment |
| Non-AOT `src/xcc` core | 32 | 3,494 | 1,412 | Mixed semantic fixes and source-shape workarounds |
| Non-AOT tests | 5 | 97 | 8 | Mostly C frontend/backend regressions |
| Specs/status docs | 3 | 269 | 8 | Before this strong-bootstrap correction |
| Other | 1 | 13 | 1 | CPython validation script |
| Total | 58 | 17,039 | 2,283 | Must be split before further broad implementation |

Untracked files at audit time include the self-hosting plan and an unrelated
OSS application document. The unrelated document must not be staged with AOT
work.

## Reusable Assets

1. `xcc.aot` diagnostics, subset checker, binder, type model, IR, lowerer, LLVM
   text emitter, native tool runner, and runtime helpers are a substantial
   Stage 0 foundation.
2. Width aliases remain ordinary Python names, and source-contract tests reject
   future-annotations and marker-style decorators.
3. Entry-driven module collection, import/alias canonicalization, and call-graph
   slicing can be reused after the root changes from `xcc.cc_driver` to the AOT
   compiler CLI.
4. Textual LLVM emission plus `llc`/link orchestration already produces a native
   executable without linking libpython.
5. CPython/native fixture infrastructure, `llc` parse tests, and native process
   execution helpers are useful oracle building blocks.
6. The current native C compiler path is a valuable final integration gate. It
   exercises file I/O, subprocess execution, LLVM C API calls, and a large
   project call graph.
7. Existing focused failures expose real runtime/lowering gaps: tuple-backed
   containers, path equality, constructor side effects, control-flow phis,
   protocol dispatch, negative indexing, and exception propagation.

These assets are reusable only after separating hosted-only code from code that
must be native reachable. A hosted analysis pass or a generated native C
compiler is not itself a bootstrap stage.

## Temporary Compatibility Layers

The following mechanisms are useful scaffolding but cannot be part of the final
strong-bootstrap proof:

- CPython `ast.parse` and direct use of CPython `ast.*` nodes throughout AOT
  parsing, binding, slicing, and lowering.
- `_bootstrap_entry_smoke_wrapper()` rooted at
  `xcc.cc_driver._aot_compile_smoke_source_to_object`.
- `_BOOTSTRAP_REQUIRED_MODULES`, which lists C compiler modules but excludes the
  `xcc.aot` compiler entry modules.
- Function-name special emitters in `llvm_text.py` that replace general lowering
  for selected compiler functions.
- No-callback preprocessor duplicates and manually initialized predefined macro
  state added because native record construction does not run ordinary
  constructor side effects.
- Protocol-to-concrete call rewrites and Protocol field casts used because the
  binder/emitter does not yet preserve concrete receiver layout and dispatch.
- Tuple-backed stand-ins for list/dict/set and path-as-string lowering whose
  equality, membership, mutation, and indexing are not yet CPython-compatible.
- Source-shape rewrites that avoid supported `for`, `break`, `reversed`, dict
  membership, tuple equality, negative indexes, comprehensions, nested
  functions, and constructor calls.
- `IrRaise -> puts + exit(2)`. This is only a temporary top-level safety guard;
  it is not exception handling and breaks caught exceptions.
- Checked-in/generated broad LLVM probes. They are diagnostics and caches, not
  valid sole inputs for Stage 1 or Stage 2.

## Strong Bootstrap Missing Components

1. A project-owned Python subset AST that is independent of CPython `ast` node
   classes.
2. A project-owned lexer and parser for the exact accepted Python subset.
3. A Stage 0-only adapter from CPython AST to the project-owned AST, used as an
   oracle and bootstrap convenience rather than a native dependency.
4. A native AOT CLI that accepts `.py` roots/entry points and emits executable,
   LLVM, source manifest, and dependency outputs.
5. Binder/lowerer migration from `ast.*` to the project-owned typed AST.
6. Explicit fallible-function ABI with result/status/error object, cross-call
   propagation, handler dispatch, and CLI-only exit conversion.
7. Correct runtime semantics for every declared-supported construct, especially
   iteration/control flow, tuple and dict value semantics, negative indexes,
   constructors, strings/bytes, and paths.
8. Native reachability of subset parser, binder, lowerer, IR emitter, runtime
   boundary, import resolver, and native CLI.
9. Stage 1->2 and Stage 2->3 build drivers that run with caches deleted and no
   Python executable available.
10. Dependency/process auditors proving no libpython, Python C API symbol, or
    Python child process; source-open evidence proving `.py` files were read.
11. Deterministic normalized LLVM, exported-symbol, and behavior equivalence
    checks between Stage 2 and Stage 3.

## Non-AOT Source Change Ledger

The checked hunk-level inventory is maintained in
`2026-07-11-aot-python-source-change-ledger.md`. The table below is its
file-level review summary; the checked ledger owns individual hunk IDs, subset
decisions, oracle status, and eventual logical commit links.

The current diff has no hunk-level ledger mapping every core source edit to a
subset decision and two-sided oracle. Therefore no broad non-AOT file is
considered proven AOT-essential. The safe classification is:

- `direct boundary`: intentional integration surface, not core language
  semantics.
- `semantic candidate`: may be a legitimate C compiler fix, but must be split
  and proven independently.
- `workaround`: changes ordinary source shape because AOT lowering/runtime did
  not support a construct declared in the subset.
- `mixed`: contains more than one class and requires hunk-level separation.

| File(s) | Current reason visible in diff/tests | Classification | Required decision/oracle before commit |
|---|---|---|---|
| `src/xcc/cc_driver.py` | Native C compile/link helper and AOT-friendly argv/file leaves | Direct boundary, secondary gate | Keep isolated from strong AOT CLI; Python CLI tests + native C smoke |
| `src/xcc/ast.py`, `src/xcc/types.py` | Declarator-op normalization and fixed record/type shapes | Mixed | Split representation fixes from constructor/tuple workarounds; parser/sema CPython tests + native behavior fixture |
| `src/xcc/lexer.py` | Bootstrap-friendly scanning/control shape | Workaround candidate | Keep source form only if construct is excluded; otherwise fix lowerer and compare token streams |
| `src/xcc/codegen.py` | Real C codegen fixes mixed with removal of dict dispatch, comprehensions, `reversed`, negative literals/indexes, nested helpers, and break-carried state | Mixed, high risk | One commit per C semantic fix with LLVM/clang oracle; supported Python constructs go back to lowerer/runtime tests |
| `src/xcc/parser/__init__.py` | Declaration/function lookahead, loop exits, optional state, helper extraction | Mixed | C parser oracle plus native parser behavior; append/break and caught-exception gaps belong to AOT semantics |
| `src/xcc/parser/array_sizes.py` | Integer scanner/evaluator expansion and type helper rewrites | Mixed | Split C constant-expression correctness from `int()`/dict/iteration avoidance |
| `src/xcc/parser/declarators.py` | Explicit pointer tuple construction and parser protocol shapes | Workaround-heavy | Fix tuple iteration/repetition and protocol binding in AOT; retain only independently tested C fixes |
| `src/xcc/parser/expressions.py` | Explicit operator branch tables, unary loop rewrite, cast/lookahead state, generic key expansion | Workaround-heavy, mixed | `for`, `break`, tuple iteration, dict lookup, negative index are supported subset features; require AOT fixes and CPython/native expression oracles |
| `src/xcc/parser/extensions.py` | Attribute scanners rewritten into explicit branches | Workaround-heavy | Fix lowerer/container semantics unless a construct is explicitly excluded; preserve parser fixture parity |
| `src/xcc/parser/statements.py`, `src/xcc/parser/type_specs.py` | Protocol typing, record/member loop exits, explicit state | Mixed | Split C grammar fixes from loop/protocol workarounds; parser tests + native AST equivalence |
| `src/xcc/preprocessor/__init__.py` | Large no-callback preprocessing path, manual macro initialization, include guards, explicit conditional-stack returns | Temporary compatibility layer, mixed | Constructor/dict/loop semantics must move to AOT runtime; retain only generic preprocessing fixes with CPython/native output oracle |
| `src/xcc/preprocessor/conditionals.py` | Explicit active-stack logic | Workaround candidate | Tuple/list iteration oracle before retaining source rewrite |
| `src/xcc/preprocessor/expressions.py` | Replaced hosted `ast.parse` expression evaluation with custom integer expression logic | Semantic candidate with strong-bootstrap value | Keep only if it is the documented C preprocessor parser; compare against existing CPython path and C oracle |
| `src/xcc/preprocessor/includes.py` | Include root/path handling and explicit searches | Mixed | Path equality belongs in runtime; include semantics require layered include/include_next oracle |
| `src/xcc/preprocessor/macros.py`, `pragmas.py`, `text.py` | Regex/dict/string/control-flow shapes expanded manually | Workaround-heavy, mixed | Supported string/container/control semantics must be fixed in AOT; C preprocessing output remains oracle |
| `src/xcc/preprocessor/process.py` | Protocol boundary and explicit stack/result flow | Mixed | Protocol dispatch/error handling belongs in binder/ABI; retain generic preprocessing fixes only |
| `src/xcc/sema/__init__.py` | Concrete analyzer access, child scopes, explicit state updates | Mixed | Constructor/protocol/loop fixes belong in AOT; semantic behavior needs CPython/native typemap oracle |
| `src/xcc/sema/constants.py` | Explicit integer candidate/limit branches and decimal parsing | Mixed | The `str | int`, global dict, and `int(text)` failures are AOT gaps; retain C literal fixes only with C/clang oracle |
| `src/xcc/sema/declarations.py`, `expressions.py`, `format_checking.py`, `initializers.py`, `layout.py`, `statements.py` | Protocol annotations, helper extraction, explicit control/container operations | Mixed, mostly small | Group by behavior, not file; existing Python tests plus native semantic oracle required |
| `src/xcc/sema/records.py`, `symbols.py`, `type_helpers.py`, `type_resolution.py` | String record keys, manual dict scan, iterative parent lookup, break-free pointer/record checks, anonymous record state | Mixed, workaround-heavy | Fix dict/tuple/constructor/loop semantics in AOT; retain only C record/type fixes with layout/sema and native oracle |

The source-shape tests named `test_*_lowers_without_*`, `test_*_avoids_*`, or
`test_*_uses_explicit_*` prove only that a particular source form is present.
They are not substitutes for CPython/native behavioral equality. The broad
native C probe gives useful integration evidence but does not identify which
individual rewrite is necessary or semantically equivalent.

## V367 Atomic Result

The focused test was completed before this audit pause:

```text
tests.test_aot_bootstrap.AotBootstrapNativeBuildTests.
test_v367_native_bootstrap_missing_include_exits_nonzero
```

Observed sequence:

1. Before the temporary safety change, the native compiler printed
   `Include not found` but returned `0`; the test failed as intended.
2. After emitting `exit(2)` for `IrRaise`, the focused test passed in 39.803s,
   returned nonzero, and produced no object.
3. A subsequent valid `stdio.c` probe returned `2` with a blank diagnostic,
   proving that `exit(2)` also terminates exceptions that should be caught.
4. An `inttypes.h` probe returned `2` with a false self-cycle, exposing the
   separate unresolved `Path` value-semantics problem tracked by V368.

No further CPython configure blocker work is authorized by this audit. V367 is
not complete until the explicit status/result ABI and supported handlers exist.

## Milestone 1 Stage 0 Baseline

The approved Milestone 1 baseline run on `codex/test-gate-hardening` at
`182d9c7` plus the preserved dirty worktree executed the six planned AOT test
modules. The first run completed 508 tests in 448.383 seconds with two failures
and one expected failure:

- the malformed source-to-LLVM leaf test asserted the obsolete two-argument
  diagnostic after the helper ABI expanded to six arguments (B271); the test
  contract was updated without changing runtime code;
- the valid standalone union native probe returned status 2 with no diagnostic,
  another witness that general `IrRaise -> exit(2)` terminates an exception
  that the Python source intends to catch (B268, V367, V380); and
- the V368 `include_next` value-semantics probe remained an expected failure.

The union failure is a frozen Stage 0 limitation, not authorization to implement
the exception ABI during Milestone 1. CPython `configure && make` was not run.

The preserved worktree was split into these logical commits before the final
Milestone 1 gate:

- `5d11369`: strong-bootstrap spec, design, audit, plan, and initial ledger;
- `a3d7932`: hosted binder function-default metadata;
- `45f404c`: AOT IR and lowerer expansion;
- `f5aeeb6`: LLVM emitter and runtime expansion;
- `2327b2d`: native oracle harness hardening;
- `4e05d45`: native C integration boundary;
- `6cf3711`: quarantined parser/bootstrap source shapes;
- `5ec8ef8`: quarantined preprocessor/bootstrap source shapes;
- `5f14f26`: quarantined sema/codegen source shapes plus B272; and
- `6dfb290`: bootstrap slicing and native gates.

The hunk ledger maps every preserved non-AOT source hunk to the applicable
integration or quarantine commit. Missing native gates remain explicit debt.

## Priority Correction

P0 is now strong-bootstrap infrastructure: project-owned AST/parser, explicit
error ABI, native AOT CLI, and `xcc.aot` reachability. P1 is runtime semantic
correctness for the declared subset. P2 is worktree decomposition and oracle
coverage. Native C compiler and CPython build blockers are P3 final integration
work and must not drive core source rewrites before P0-P2 are established.
