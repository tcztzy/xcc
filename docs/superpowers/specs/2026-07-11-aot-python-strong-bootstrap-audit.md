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

The final six-module AOT gate after the split ran 508 tests in 505.034 seconds.
It had exactly one failure, the frozen B268/V367/V380 valid-union status-2
failure, plus the V368 expected failure. B271 and B272 were corrected as stale
test ABI assertions. `uv run tox -e lint` and `uv run tox -e type` both passed.
The Stage 0 freeze tag is `aot-stage0-m1-20260711`; it is a Milestone 1 baseline,
not evidence of Stage 1 or strong self-hosting.

## Milestone 2 Contract Result

Milestone 2 replaces the direct CPython-AST common path with an immutable,
project-owned AST. `ast.parse` now appears in production AOT code only in
`cpython_ast_adapter.py`, which is one of three explicit Stage 0-only modules.
`AotModule`, type-default metadata, subset validation, binder, lowerer, slice,
and native oracle helpers all consume owned nodes. The adapter converted every
active `src/xcc` module with zero `UnsupportedNode` values across the 77-node
active inventory. Owned child sequences are tuples; spans and child edges are
constructor inputs; structural rendering does not depend on CPython-generated
text. Span tests freeze 1-based lines, 0-based UTF-8 byte columns, and
end-exclusive positions.

The source contract now binds parser kind to its callback, reads and hashes
each UTF-8 source once, retains that exact source and owned AST for downstream
analysis, includes nested static imports and parent package initializers,
records allowed stdlib roots, rejects unknown external roots, and emits a
canonical version-1 manifest in dependency/SCC order. A subset backend rejects
`xcc.aot.__main__`, `xcc.aot.hosted_cli`, and
`xcc.aot.cpython_ast_adapter`. Milestone 2 performs no persistent cache reads
or writes; the manifest separately records an explicit `--no-cache` request.

The hosted and native command surfaces accept the same required build options,
tool paths, and duplicate/unknown-option rules. Native mode rejects both joined
and separated CPython parser selection even when `--help` is also present. The
Stage 0 acceptance command built `build/aot/contract/hosted-xcc-aot`; the
resulting executable reports `xcc-aot 0.2 native-contract`, rejects
`--parser=cpython`, and links without libpython. The emitted Python entry is
namespaced to avoid collision with the C process `main`. LLVM normalization is
limited to declared metadata lines and cannot rewrite path-shaped program
constants.

This artifact is deliberately only the native CLI contract shell. Its native
`build --parser=subset` path reports that the pipeline is unavailable before
Milestone 5. It does not contain the project parser, does not prove compiler
layer reachability, and is not Stage 1. The project-owned lexer/parser remains
Milestone 3; status/error ABI and runtime semantics remain Milestone 4; native
source loading, hash/manifest operations, compiler call-graph closure, and tool
spawning remain Milestone 5/6. No CPython `configure && make` work was run, and
no non-`src/xcc/aot` compiler-core source was modified for Milestone 2.

The final fast Milestone 2 AOT gate ran 505 tests in 22.773 seconds with no
failures. `uv run tox -e lint` and `uv run tox -e type` passed. The complete
bootstrap module then ran 84 tests in 1306.630 seconds with exactly the frozen
B268/V367/V380 valid-union status-2 failure and the V368 expected failure; it
had no new failure or error. During that gate, B284 exposed that the secondary
native C slice's flat short-name class table mixed the new owned
`py_ast.FunctionDef` with the C compiler's `ast.FunctionDef`. All-source
admission still covers every native candidate, while the secondary C compiler
slice now excludes `xcc.aot` implementation modules it cannot reach. This is a
boundary fix, not evidence for AOT compiler reachability.

The Milestone 2 implementation is split into `7c2ea83` (owned AST and common
frontend migration) and `fb792da` (source, CLI, tool, and bootstrap boundary
contracts). The following status/spec commit records the acceptance evidence;
none of these commits includes the unrelated OSS application document.

## Milestone 3 Project-Owned Parser Result

Milestone 3 adds a hand-written, deterministic Python lexer and
recursive-descent/Pratt parser. They use no CPython AST objects, `ast.parse`,
generated parser tables, required cache, marker decorator, pragma, or comment
directive. The lexer implements indentation, implicit/explicit continuation,
identifiers, numeric and string tokens, comments, operators, and 1-based
line/0-based UTF-8 byte spans. The parser constructs the immutable 77-kind
owned AST surface, including functions/classes, imports, annotations, control
flow, exception/with forms, calls, containers, comprehensions, slices, adjacent
strings, bytes, and nested f-string format specifications.

The Stage 0 oracle compares every semantic field, end-exclusive span, and
ordered child edge. All 67 current `src/xcc` files and 436,377 CPython tokens
match. Stable `XCC-AOT-PYLEX-*` and `XCC-AOT-PYPARSE-*` diagnostics cover the
documented rejection boundary. The common `module.parse_source` path now uses
the owned parser; tests that deliberately exercise a later checker/lowerer
rejection construct their hosted oracle AST explicitly.

`xcc.aot.parser_oracle` is a fourth explicit Stage 0-only module alongside
`__main__`, `hosted_cli`, and `cpython_ast_adapter`. The acceptance command

```text
uv run python -m xcc.aot parser-oracle \
  --source-root src/xcc --entry xcc.aot.cli:main
```

reported `checked=63`, the full deterministic `xcc.aot.cli` dependency
closure, and `failures=[]`. The subset closure contains `xcc.aot.py_lexer` and
`xcc.aot.py_parser` and contains none of the four hosted-only modules.

The hosted Stage 0 command also completed a no-cache subset build from source:

```text
uv run python -m xcc.aot build --parser=subset --no-cache \
  --source-root src/xcc --entry xcc.aot.cli:main \
  --emit-normalized-ir build/aot/parser/subset.ir \
  --output build/aot/parser/subset-xcc-aot
```

The result is a 37 KiB arm64 Mach-O CLI contract shell. It reports the native
contract version/help, links only `libSystem`, and has no unresolved Python
symbols. `subset.reachability` records the parser source closure and explicitly
sets `native_call_graph=false`; it is not an emitted compiler call graph, not
Stage 1, and not evidence for Milestone 5. Exception/status ABI work remains
Milestone 4, and native source loading plus parser/binder/lowerer/emitter/tool
reachability remains Milestone 5.

The final fast AOT gate ran 527 tests across 14 modules with no failures.
`uv run tox -e lint` and `uv run tox -e type` passed. The complete bootstrap
module ran 84 tests in 1348.607 seconds with exactly the frozen
B268/V367/V380 conditional-include/union status-2 failure and the V368 expected
failure; it had no new failure or error, and the V367 focused test passed. No
CPython `configure && make` work and no non-`src/xcc/aot` compiler-core source
change was performed.

The implementation is split into `80b76c9` (owned lexer), `3a83009` (owned
parser), `c08cf82` (hosted oracle, common/backend boundary, and subset CLI), and
`4b95eb2` (explicit hosted unsupported-form test oracles). The following
status/spec commit records this evidence; none of these commits includes the
unrelated OSS application document.

## Milestone 4 Exception/Runtime Result

Milestone 4 replaces the temporary default-return/process-exit exception path
with a compositional native ABI:

```text
status fn(args..., result_out, error_out)
```

Fallibility is propagated through the project call graph. Error records carry
the exception type, message, source span, and typed payload; lowered handlers
dispatch through exception ancestry, and supported rethrow, `try` `else`, and
`finally` control flow execute without converting an inner error directly into
a process exit. The generated process `main` is the sole uncaught-error stderr
and exit boundary. The source-to-LLVM wrapper now uses its ordinary Python
`try/except` body and generic status emission rather than a private emitter or
bodyless leaf.

The supported runtime subset now has CPython/native behavior oracles for
`for`/`while`/`break`/`continue`, tuple comparison and membership, dict lookup,
membership and mutation, negative indexing, constructors, string/bytes
operations, and `Path` equality. Loop exits reached by `break` merge values
from the actual break predecessor, so assignments made in the current
iteration are preserved. This fixed anonymous-record typedef compilation in
the real native driver without rewriting the parser. H419/H420 were retired to
ordinary `while True`/`break`, with their CPython and native oracles recorded in
the source-change ledger.

Current acceptance evidence:

- the four planned status/runtime/IR/LLVM modules pass 389/389 tests in 6.234s;
- `/opt/homebrew/opt/llvm/bin/llc` accepts
  `build/aot/status/status-oracle.ll` and emits an arm64 Mach-O object;
- the advertised real-bootstrap parseability test now invokes `llc` and passes;
- the complete bootstrap module passes 85/85 tests in 4550.733s, including the
  native smoke, configure-style object/link fixture, conditional
  include/union/anonymous typedef suite, V367 missing-include diagnostic, and
  V368 `include_next` object oracle; V368 is no longer an expected failure;
- `uv run tox -e lint`, `uv run tox -e type`, and `git diff --check` pass.

The implementation is split across `435c7e2` (status ABI), `74bc292` (typed
handlers), `1e5012e` (runtime value semantics), `2cad22a` (first workaround
retirement), `41f074b` (real bootstrap runtime closure), and `933d519` (final
native semantics and integration closure). No CPython `configure && make` work
was run. The known B325/B326 complete-`py311` baseline failures were not
retested or expanded in this milestone. T4 is complete, but this is not
Milestone 5 native `xcc.aot` reachability, not Stage 1, and not strong-bootstrap
completion.

## Priority Correction

P0 is now strong-bootstrap infrastructure: project-owned AST/parser, explicit
error ABI, native AOT CLI, and `xcc.aot` reachability. P1 is runtime semantic
correctness for the declared subset. P2 is worktree decomposition and oracle
coverage. Native C compiler and CPython build blockers are P3 final integration
work and must not drive core source rewrites before P0-P2 are established.
