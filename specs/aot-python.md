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
- file: `src/xcc/aot/py_ast.py` -> immutable project-owned subset AST.
- planned file: `src/xcc/aot/py_lexer.py` -> project-owned subset lexer.
- planned file: `src/xcc/aot/py_parser.py` -> project-owned subset parser.
- file: `src/xcc/aot/cpython_ast_adapter.py` -> Stage 0-only CPython AST
  adapter to the project-owned AST.
- file: `src/xcc/aot/source_contract.py` -> source snapshot, dependency order,
  parser/cache policy, and canonical manifest contract.
- file: `src/xcc/aot/cli.py` -> subset-compatible native CLI root;
  `src/xcc/aot/hosted_cli.py` and `src/xcc/aot/__main__.py` -> Stage 0 process
  adapter exposing the same build options.
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
T1|x|freeze current hosted Stage 0 and split the large worktree into bisectable logical commits|V379,V382,V384
T2|x|define strong-bootstrap source contract, project-owned AST, and hosted/native AOT CLI|V369,V374,I.cmd
T3|x|implement project-owned subset lexer/parser and CPython-AST oracle adapter|V370,V372,V373
T4|x|implement explicit exception/status ABI and required native runtime semantics|V367,V368,V375,V380
T5|~|make `xcc.aot` parser/binder/lowerer/emitter/CLI native-reachable|V376,V383
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
B272|2026-07-11|four direct codegen helper tests retained the old `_compare` call shape after null-pointer-constant evidence became explicit ABI inputs|V384
B273|2026-07-11|all-source admission treated the reflective CPython AST adapter as a native candidate because Stage 0-only modules had no explicit production boundary|V370,V383
B274|2026-07-11|the initial CLI artifact test assumed emitted LLVM began with a `ModuleID` comment instead of checking the stable entry symbols|V384
B275|2026-07-11|the AOT CLI used ordinary one-argument `print`, but statement lowering did not connect that supported source form to the existing `IrPrint` emitter/runtime path|V374,V376
B276|2026-07-11|the hosted CLI emitted the Python entry function as `main`, colliding with the generated C process wrapper symbol|V376,V384
B277|2026-07-11|source resolution discarded its decoded source/owned AST, so the CLI reread and reparsed an entry after hashing it and could compile a different snapshot than the manifest|V372,V384
B278|2026-07-11|owned AST metadata required hosted `object.__setattr__`, frozen nodes contained mutable lists, and common rendering fell back to CPython-generated text|V370,V384
B279|2026-07-11|the CPython-free string-annotation recognizer drifted from the accepted grammar by accepting numeric `Literal`, rejecting grouped union/empty tuple forms, and mishandling escaped quotes|V374,V379
B280|2026-07-11|the native CLI entry briefly called an omitted helper and then compared an inferred i64 loop index with `argc:int32`, producing unresolved or invalid LLVM in the real build|V376,V384
B281|2026-07-11|LLVM normalization replaced the source-root text globally and could alter semantic string constants rather than metadata only|V377,V384
B282|2026-07-11|source closure scanned only top-level imports, omitted parent package initializers, silently ignored unknown externals, and allowed a subset manifest to include hosted-only modules|V370,V372,V384
B283|2026-07-11|native-candidate admission rejected the owned AST's ordinary `dataclass(frozen=True, kw_only=True)` declaration because the decorator subset allowed only `frozen`|V370,V374
B284|2026-07-11|the secondary native C bootstrap preloaded every module into a flat short-name class table, so `xcc.aot.py_ast.FunctionDef` displaced `xcc.ast.FunctionDef` and lost `is_variadic`|V376,V381,V383
B285|2026-07-11|the first owned lexer emitted `NEWLINE` end spans after advancing to the next physical line instead of at the end of the newline token|V370,V384
B286|2026-07-11|the owned lexer treated the empty EOF sentinel as a member of character-class strings, accepting a trailing line-continuation backslash and taking incorrect numeric/string EOF branches|V370,V384
B287|2026-07-11|the first owned parser routed tuple/set display elements through non-star expression branches, rejecting active `(*items, ...)` and `{item, *items}` displays|V370,V374
B288|2026-07-11|the owned numeric decoder tested for exponent letters before radix prefixes, so valid hexadecimal integers containing `e`/`E` were sent to decimal float conversion|V370,V374,V384
B289|2026-07-11|the owned statement dispatcher treated the soft keyword `match` as reserved and rejected an ordinary active assignment to a variable named `match`|V370,V374
B290|2026-07-11|the owned parser discarded grouping-delimiter extents, so enclosing expressions and statements ended at the inner node instead of the closing parenthesis|V370,V384
B291|2026-07-11|formatted-string children used each token's span instead of CPython's full adjacent-string expression span|V370,V384
B292|2026-07-11|a generator expression used as the sole call argument omitted the call parentheses from its span|V370,V384
B293|2026-07-11|an open-ended slice selected its lower bound as the span end and omitted the consumed colon|V370,V384
B294|2026-07-11|owned tuple nodes ended at their final element and omitted a trailing comma from the CPython-compatible source span|V370,V384
B295|2026-07-11|grouping extent lookup selected the oldest record, so nested parentheses propagated the inner opening delimiter to enclosing nodes|V370,V384
B296|2026-07-11|the common `module.parse_source` boundary retained a function-local CPython adapter import, so static subset dependency closure still reached the hosted parser|V370,V376
B297|2026-07-11|the owned numeric decoder annotated its heterogeneous literal result with `complex`, which is intentionally outside the binder's declared annotation subset, preventing the parser from admitting itself|V370,V374,V383
B298|2026-07-11|switching the common parse boundary to the owned parser dropped the public `invalid syntax` diagnostic prefix expected by the CPython-compatible API|V379,V384
B299|2026-07-11|the first status-ABI LLVM test asserted a nonexistent dot in generated string symbols and omitted the required varargs function type from `dprintf` call syntax|V380,V384
B300|2026-07-11|the first uncaught-error wrapper named both its error-record alloca and a basic block `%error`, so `llc` rejected the otherwise structurally correct status ABI|V380,V384
B301|2026-07-11|the LLVM private-helper regression still called the removed temporary `_emit_status_return` path after status/error records replaced type-default raise returns|V380,V384
B302|2026-07-11|fallibility pre-analysis raised a raw `AssertionError` for deliberately malformed IR before the LLVM validator could emit its stable `XCC-AOT-LLVM-0001` diagnostic|V380,V384
B303|2026-07-11|bootstrap slice call rewriting and dependency scans omitted the new `IrTry` variant and discarded `IrRaise` span/payload data|V376,V380,V384
B304|2026-07-11|the new slice raise-call scan reused a branch-local `targets` name already inferred as `list[str]`, violating the tuple return contract under mypy|V379,V384
B305|2026-07-11|the initial status/slice additions left import ordering and one fallibility predicate line outside the repository's ruff format contract|V379,V384
B306|2026-07-11|eight lowerer regressions encoded the temporary handler whitelist and `try -> IrIf(True)` flattening instead of the required structured status/handler IR|V375,V380,V384
B307|2026-07-11|the structured-handler implementation inserted `IrTry` after `IrTuple` in two source import blocks, violating deterministic ruff ordering|V379,V384
B308|2026-07-11|the first handler ancestry helper duplicated and was overwritten by the emitter's existing `_record_extends` method with a different signature|V380,V384
B309|2026-07-11|the typed-error payload fixture omitted the subset-required `__init__ -> None` annotation and retained the pre-payload `IrRaise` expectation|V374,V380,V384
B310|2026-07-11|tuple literal lowering passed the container `IrTupleType` as each element's expected type, rejecting integer tuples used by ordinary `for` and negative-index code|V375,V384
B311|2026-07-11|only empty dict literals had a tuple-backed lowering path, so supported nonempty `dict[K, V]` initialization failed before membership or mutation semantics ran|V375,V384
B312|2026-07-11|the bytes-size constructor allocated embedded NUL bytes but string-style `len` used `strlen`, reporting every `bytes(n)` value as length zero|V368,V375
B313|2026-07-11|Path equality compared pointer representations, so separately materialized but equal parent/path values compared unequal|V368,V375
B314|2026-07-11|tuple equality and nested tuple membership compared allocation pointers instead of recursively comparing CPython-visible element values|V368,V375
B315|2026-07-11|string `__getitem__` applied a signed negative index directly to the data pointer instead of normalizing it against the string length|V368,V375
B316|2026-07-11|dict membership reused tuple membership and compared the needle with each key/value pair object rather than with the pair's key|V368,V375
B317|2026-07-11|the first bytes-header patch matched the string zero-buffer allocator's similar prologue, leaving `%total` undefined there and `%data` undefined in `int.to_bytes`|V368,V384
B318|2026-07-11|introducing a distinct dict IR type left method dispatch and Parser singleton-scope construction guarded by the obsolete tuple type, rejecting supported `get`/`items`/`setdefault` calls and dropping initial dict scopes|V368,V375,V384
B319|2026-07-11|the first length-aware bytes object allocated no trailing zero beyond its logical payload, so exporting its data pointer to C string APIs could read past the allocation|V368,V376,V384
B320|2026-07-11|IR regressions still asserted the obsolete tuple-backed-dict and string-backed-bytes type identities after those values gained distinct semantic types|V384
B321|2026-07-11|the distinct bytes expression variant was imported but omitted from bootstrap slice call-target exhaustiveness, while adjacent imports and type predicates missed lint normalization|V376,V379,V384
B322|2026-07-12|the quarantined record-member parser rewrote ordinary `while True`/`break` into a loop flag even after native lowering and runtime behavior supported the accepted control flow|V375,V382,V384
B323|2026-07-12|the distinct bytes representation implemented indexing and length but omitted bytes slicing, `ljust`, and optional-bytes narrowing, so the real bootstrap stopped at `_const_from_bytes`|V368,V375,V376
B324|2026-07-12|the Milestone 3 uncaught-error oracle still expected diagnostics on stdout after the status ABI moved the sole process-boundary diagnostic to stderr|V380,V384
B325|2026-07-12|the first complete `py311` run exposed a pre-existing C parser rejection of overloadable function declarations with parenthesized function-pointer parameters|V379
B326|2026-07-12|the first complete `py311` run exposed a pre-existing C parser diagnostic drift where an unsupported `?` unary operator reached integer-literal parsing|V379
B327|2026-07-12|the bytes runtime gained a distinct object ABI but the native process wrapper still rejected bytes-valued entry results instead of writing their length-aware payload|V368,V375,V384
B328|2026-07-12|the length-aware bytes main-wrapper write call exceeded the repository's 100-column lint contract|V379,V384
B329|2026-07-12|full-slice lowering narrowed `bytes | None` names to bytes in IR, but the emitter retained the pre-guard union type and rejected an ABI-compatible bytes slice operand|V368,V375,V384
B330|2026-07-12|value-producing boolean lowering merged tuple operands but not dict operands, so `typed_dict or {}` inherited an enclosing integer fallback and the real bootstrap emitter rejected a dict value as `int`|V375,V384
B331|2026-07-12|record construction aligned call operands directly with stored fields, so custom exception constructors that accepted an unstored message shifted every typed payload field and made status-error emission ill-typed|V380,V384
B332|2026-07-12|the real bootstrap emitter regression retained the pre-status two-argument entry-call assertion after the process wrapper gained explicit result and error out-parameters|V380,V384
B333|2026-07-12|native-reachability assertions hard-coded pre-status helper return types, so correctly fallible preprocessor symbols appeared absent after transitive status analysis changed their ABI|V376,V380,V384
B334|2026-07-12|the return-type-agnostic bootstrap assertion located a helper's first call site instead of its later definition, so body-shape checks inspected the caller after status propagation introduced that call|V380,V384
B335|2026-07-12|the constructor-field binding guard exceeded the repository's 100-column lint contract|V379,V384
B336|2026-07-12|the first manual wrap of the constructor-field guard passed line length but not the repository's canonical ruff formatter layout|V379,V384
B337|2026-07-12|the bootstrap test named `llc_parseable` only wrote LLVM text and never invoked `llc`, allowing malformed pointer arithmetic to pass its advertised gate|V376,V384
B338|2026-07-12|bytes concatenation and repetition lowered through generic integer `IrBinary`, emitting invalid `add ptr`/`mul ptr` in the real codegen closure|V368,V375,V384
B339|2026-07-12|after bytes gained a distinct object ABI, `str.encode()` retained its old C-string identity lowering, producing a mixed string/bytes concat in the real codegen closure|V368,V375,V384
B340|2026-07-12|bytes `for` iteration reused tuple length/get semantics and exposed each element as a pointer, so integer shifts in the real codegen closure emitted `shl i64 ptr`|V368,V375,V384
B341|2026-07-12|a legacy source-to-LLVM wrapper emitter bypassed its structured `IrTry` and hard-coded a pre-status direct call to a fallible helper, returning null into the native file writer|V376,V380,V384
B342|2026-07-12|the source-to-LLVM wrapper remained a bodyless native-emitted leaf after its legacy emitter was removed, replacing its ordinary Python `try/except` body with `ret null`|V376,V380,V384
B343|2026-07-12|`raise exception_factory()` used the factory's textual call target as the runtime error tag instead of its declared exception-record return type, bypassing matching typed handlers|V375,V380,V384
B344|2026-07-12|the first factory-aware raise patch unconditionally lowered every exception constructor as an ordinary call, rejecting supported built-in `ValueError(...)` raises before their status boundary|V380,V384
B345|2026-07-12|the bootstrap CLI converted a caught compile error to result code 2 while preserving its error record, but the process wrapper printed diagnostics only for nonzero ABI status and silently discarded the message|V367,V380,V384
B346|2026-07-12|conditional-expression lowering narrowed only the true branch, so `current() if token is None else token` retained `Token | None` in the else branch and blocked factory-method reachability|V375,V384
B347|2026-07-12|LLVM loop exits reused the condition-header value after `break`, discarding assignments from the current iteration and making an anonymous-record typedef appear incomplete|V375,V384
B348|2026-07-12|an optional-receiver regression still expected `Type | None` in the `x is None` conditional-expression else arm after B346 correctly narrowed that arm to `Type`|V375,V384
B349|2026-07-12|a legacy malformed-leaf regression retained the removed source-to-LLVM special emitter's private signature contract after the wrapper moved to generic status-aware emission|V376,V380,V384
B350|2026-07-12|the bytes-concatenation runtime addition exceeded the repository's 100-column lint contract in one emitted `memcpy` line|V379,V384
B351|2026-07-12|new bytes/status/loop-exit emitter lines passed length checks but not the repository's canonical ruff formatter layout|V379,V384
B352|2026-07-12|the bootstrap entry integration test retained a pre-status two-argument smoke-compiler definition assertion after fallibility analysis added result/error out-parameters|V380,V384
B353|2026-07-12|adjacent bootstrap integration assertions still expected direct bool/pointer returns from three now-fallible source compilation helpers instead of status/result/error calls|V380,V384
B354|2026-07-12|the V368 `include_next` native probe retained an `expectedFailure` marker after path value semantics made the full compile/object oracle pass|V368,V384
B355|2026-07-14|binder field inference dropped homogeneous list literals assigned in `__init__`, so the owned lexer lost `self.indents` before native call-graph lowering|V376
