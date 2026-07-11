# XCC AOT Python Strong Bootstrap Spec

## §G GOAL
Compile the documented XCC-Python subset from ordinary `.py` source to native
machine code, keep the same source runnable on CPython 3.11+, and close a strong
bootstrap loop in which native Stage 1 builds Stage 2 and native Stage 2 builds
Stage 3 without CPython, libpython, `ast.parse`, or pre-generated AST/IR as a
required runtime input.

## §C CONSTRAINTS
- Source syntax ! strict CPython 3.11 subset; custom syntax ⊥.
- Marker decorators, AOT pragmas, comment directives, and annotation directives ⊥.
- Width aliases such as `int32`, `int64`, `uint64`, and `usize` ! ordinary
  Python-visible annotations or aliases with valid CPython behavior.
- Runtime source dependencies = Python standard library only under CPython;
  produced native stages ! depend on neither CPython nor libpython.
- Stage 0 may use CPython `ast.parse` through a hosted adapter.
- Stage 1/2/3 source parsing ! use the project-owned XCC-Python lexer/parser and
  project-owned AST model.
- Checked-in AST, serialized IR, generated LLVM, and generated code may be
  caches or diagnostics; sole bootstrap input ⊥.
- Allowed native build tools = configured LLVM `llc`, system assembler, system
  linker, and platform C runtime.
- AOT runtime/binder/lowerer bugs ! fixed in AOT-owned code for constructs in
  the accepted subset; rewriting compiler core source to dodge them ⊥.
- A non-AOT source rewrite is allowed only after the construct is explicitly
  excluded from the subset and CPython behavior is preserved with an oracle.
- Existing C compiler and target specs remain separate; native C compilation
  and CPython `configure && make` are integration gates, not bootstrap proof.
- GPL-derived sources/tests ⊥.
- Handoff after code edit ! `uv run tox -e lint` & `uv run tox -e type`.

## §I INTERFACES
- Stage 0 = CPython runs `xcc.aot` and may use the CPython AST adapter to build
  native `build/aot/stage1/xcc-aot`.
- Stage 1 = first native AOT compiler; reads repository `.py` files and builds
  `build/aot/stage2/xcc-aot` with the project-owned subset frontend.
- Stage 2 = native compiler built by Stage 1; reads the same `.py` source set and
  builds `build/aot/stage3/xcc-aot`.
- Stage 3 = stability witness built by Stage 2; compared with Stage 2 by
  normalized LLVM, exported symbols, and behavior fixtures.
- planned cmd: `uv run python -m xcc.aot build --parser=cpython --source-root
  src/xcc --entry xcc.aot.cli:main --output build/aot/stage1/xcc-aot`.
- planned cmd: `build/aot/stage1/xcc-aot build --parser=subset --no-cache
  --source-root src/xcc --entry xcc.aot.cli:main --output
  build/aot/stage2/xcc-aot`.
- planned cmd: `build/aot/stage2/xcc-aot build --parser=subset --no-cache
  --source-root src/xcc --entry xcc.aot.cli:main --output
  build/aot/stage3/xcc-aot`.
- planned file: `src/xcc/aot/py_ast.py` -> project-owned subset AST.
- planned file: `src/xcc/aot/py_lexer.py` -> project-owned subset lexer.
- planned file: `src/xcc/aot/py_parser.py` -> project-owned subset parser.
- planned file: `src/xcc/aot/cpython_ast_adapter.py` -> Stage 0-only CPython AST
  adapter to the project-owned AST.
- planned file: `src/xcc/aot/cli.py` and `src/xcc/aot/__main__.py` -> identical
  hosted/native build CLI contract.
- file: `src/xcc/aot/binder.py` -> type and symbol binding over project-owned AST.
- file: `src/xcc/aot/ir.py` -> target-independent AOT IR.
- file: `src/xcc/aot/lower.py` -> typed AST to AOT IR.
- file: `src/xcc/aot/llvm_text.py` -> deterministic textual LLVM emission.
- file: `src/xcc/aot/core_runtime.py` -> native subset runtime.
- file: `docs/superpowers/specs/2026-07-11-aot-python-strong-bootstrap-audit.md`
  -> current gap and source-change ledger.
- file: `docs/superpowers/specs/2026-07-11-aot-python-source-change-ledger.md`
  -> Milestone 1 hunk-level non-AOT source inventory and oracle status.
- file: `docs/superpowers/specs/2026-06-26-aot-python-design.md` -> architecture.
- file: `docs/superpowers/plans/2026-07-06-aot-python-self-hosting.md` -> execution plan.

## §V INVARIANTS
V367: Native AOT `raise` without a matching lowered handler ! propagate a
fallible status/result across calls and reach a nonzero CLI exit; returning a
type-default value onto a success path ⊥.
V368: AOT runtime value semantics for supported objects ! match CPython-visible
behavior; pointer identity for `Path`, tuple, string, or dict key equality ⊥.
V369: Strong bootstrap chain ! Stage0(CPython)->Stage1(native)->Stage2(native)->Stage3(native).
V370: Stage 1/2/3 Python source parse ! project-owned lexer/parser -> project-owned AST; `ast.parse` and CPython AST objects ⊥ reachable.
V371: Stage 1/2 build/link dependency closure ! no libpython, Python C API symbol, Python executable, or Python module loading.
V372: Stage 1 and Stage 2 ! actually open/read the declared repository `.py` inputs during `--no-cache` builds.
V373: Checked-in AST/IR/generated code ! optional cache only; deleting cache still permits Stage 1->2 and Stage 2->3.
V374: Source contract ! CPython 3.11-valid syntax, no marker decorator/pragma/directive, width types remain ordinary annotations/aliases.
V375: Supported `for`/`break`/tuple/dict/index/`try` semantics ! implemented in binder/lowerer/runtime; source-shape avoidance ⊥ substitute.
V376: Native compile reachability gate ! includes subset lexer/parser, binder, lowerer, IR emitter, runtime boundary, and native CLI in the emitted call graph.
V377: Stage 2 and Stage 3 ! equivalent normalized LLVM, exported symbols, and specified behavior fixtures; unexplained drift ⊥.
V378: Native external process allowlist = `llc`, assembler, linker; any Python executable ⊥.
V379: CPython reference path ! imports/runs on CPython 3.11+ and passes full Python tests plus lint/type gates.
V380: Fallible AOT ABI ! explicit status/result/error object, handler type dispatch, cross-call propagation, and CLI-only process exit.
V381: Native C compiler smoke and CPython `configure && make` ! final secondary gates only; neither proves V369-V380.
V382: Every non-`src/xcc/aot` source change for AOT ! ledger reason + subset decision + CPython oracle + native oracle or explicit missing-gate status.
V383: All-source admission ! syntax/type preflight only; it cannot satisfy V376 or any strong-bootstrap stage gate.
V384: Bootstrap outputs ! deterministic module ordering, source manifest, normalized IR, and reproducible diagnostics.

## §T TASKS
id|status|task|cites
T1|.|freeze current hosted Stage 0 and split the large worktree into bisectable logical commits|V379,V382,V384
T2|.|define strong-bootstrap source contract, project-owned AST, and hosted/native AOT CLI|V369,V374,I.cmd
T3|.|implement project-owned subset lexer/parser and CPython-AST oracle adapter|V370,V372,V373
T4|.|implement explicit exception/status ABI and required native runtime semantics|V367,V368,V375,V380
T5|.|make `xcc.aot` parser/binder/lowerer/emitter/CLI native-reachable|V376,V383
T6|.|build Stage 1 from Stage 0 and verify native dependency closure|V369,V371,V378
T7|.|build Stage 2 from `.py` with Stage 1 and no Python process/cache dependency|V369,V370,V371,V372,V373,V378
T8|.|build Stage 3 with Stage 2 and prove normalized IR/symbol/behavior stability|V369,V377,V384
T9|.|run CPython compatibility, native C compiler, CPython build, lint, type, and full tests|V379,V381

## §B BUGS
id|date|cause|fix
B268|2026-07-11|native AOT lowered nested frontend `raise` to a type-default return, so errors could report success or continue into null dereference|V367,V380
B269|2026-07-11|native AOT used object identity where supported `Path` value equality was required, so `#include_next` could revisit the same root|V368
B270|2026-07-11|bootstrap acceptance was rooted at the native C driver and all-source hosted admission while `xcc.aot` was absent from native reachability and depended on `ast.parse`|V369,V370,V376,V381,V383
B271|2026-07-11|the malformed source-to-LLVM leaf regression asserted the obsolete two-argument ABI after the helper gained include, define, undefine, and language inputs|V384
