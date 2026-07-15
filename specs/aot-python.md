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
T5|x|make `xcc.aot` parser/binder/lowerer/emitter/CLI native-reachable|V376,V383
T6|x|build Stage 1 from Stage 0 and verify native dependency closure|V369,V371,V378
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
B356|2026-07-14|cross-module function signatures retained imported project type qualifiers such as `ast.Module`, but lowerer record lookup recognized only unqualified class names|V376
B357|2026-07-14|binder constructor-field inference ignored local assignments and imported function return signatures, so `self.tokens = lex_python(...)` lost its tuple element type before native lowering|V376
B358|2026-07-14|lowerer treated module-qualified project classes such as `ast.Name` as instance fields, blocking both native `isinstance` checks and owned-AST constructors|V376
B359|2026-07-14|lowerer had no value representation for zero-argument record constructors stored in global dicts, so the owned parser could not call the operator class selected by token text|V376
B360|2026-07-14|`isinstance(items[index], Record)` did not narrow the stable subscript slot, so assigning that slot to a local erased the concrete record fields used by the owned parser|V376
B361|2026-07-14|AOT record layouts omitted inherited dataclass fields and constructor keyword-only metadata, so owned AST subclasses could neither store nor read the common `span` prefix|V376
B362|2026-07-14|binder and lowerer omitted annotated `*args` from function signatures, leaving the owned parser's `_children(*values)` body unbound and its callers ABI-incompatible|V376
B363|2026-07-14|native object lowering treated the built-in `Ellipsis` singleton as an unknown name, preventing the owned parser from constructing `Constant(...)` for `...` source|V376
B364|2026-07-14|native `isinstance` accepted only a partial built-in type-marker set and could not narrow bytes-valued unions used by owned string-literal parsing|V376
B365|2026-07-14|statement lowering applied only the first `isinstance` narrowing in an `and` chain, so later guarded values retained their base record type in the owned parser|V376
B366|2026-07-14|the native string subset omitted `str.rfind`, blocking source-position calculation in the owned parser despite an existing forward-search path|V376
B367|2026-07-14|the native string subset omitted `str.count`, blocking line-number calculation from the owned parser's source prefix|V376
B368|2026-07-14|the owned numeric decoder's ordinary two-argument `complex` construction had no native opaque-value representation, even though complex annotations remain outside the bootstrap subset|V376
B369|2026-07-14|AOT lowering incorrectly modeled `for ch in str` with bytes semantics and bound `ch` as an integer, blocking ordinary string methods in the owned integer decoder|V376
B370|2026-07-14|tuple-backed mutable containers omitted `list.clear`, blocking positional-parameter state reset in the owned parser|V376
B371|2026-07-14|native lowering omitted `any`/`all` over generator predicates, blocking the owned parser's default-parameter ordering check|V376
B372|2026-07-14|slice class-table preanalysis omitted current-module import aliases, so inferred constructor fields diverged from the later lowered constructor ABI|V376
B373|2026-07-14|loop and branch phis collapsed `bool | None` to `bool`, making native identity/equality unable to distinguish `None` from `False` in the owned string parser|V376
B374|2026-07-14|guard fallthrough analysis recognized only syntactic `raise`/`return`, so calls annotated `NoReturn` failed to propagate `isinstance` narrowing in the owned parser|V376
B375|2026-07-14|native `bytes` construction accepted only an integer size and rejected tuple-backed integer iterables used by the owned bytes-literal decoder|V376
B376|2026-07-14|the LLVM emitter accepted only a single-string `str.endswith` suffix even though lowering preserved the ordinary tuple-of-strings form used by the owned numeric decoder|V376
B377|2026-07-14|tuple-backed runtime storage could box integers, booleans, and pointers but not floating-point values, so the owned numeric decoder could not return a float through its opaque result ABI|V368,V376
B378|2026-07-14|native equality dispatch omitted two floating-point operands and fell through to pointer comparison, preventing typed float containers from preserving CPython-visible equality|V368,V376
B379|2026-07-14|negative `isinstance` guard refinement required a function exit and ignored `continue`, so a loop path that could reach later statements retained the base record layout in the owned binder|V375,V376
B380|2026-07-14|the native string predicate subset omitted `str.isidentifier`, blocking dotted project-type validation in the owned binder|V368,V376
B381|2026-07-14|the native string subset implemented only left-to-right `split`, so bounded `str.rsplit` could not preserve the qualified-name leaf used by the owned binder|V368,V376
B382|2026-07-14|the native string predicate subset omitted `str.isupper`, blocking the owned binder's structural project-type reference check|V368,V376
B383|2026-07-14|exact `object` values used untagged pointer guesses, so the owned AST renderer could neither implement dynamic `repr` nor distinguish primitive types across native call and field boundaries|V368,V376
B384|2026-07-14|the native lowerer accepted builtin type markers as values but omitted `type(value)`, so exact runtime type identity such as `type(value) is int` could not preserve CPython's `bool`/`int` distinction in the owned binder|V368,V376
B385|2026-07-14|record narrowing compared qualified union members such as `ast.expr` directly with the unqualified class table, so a valid `isinstance(value, ast.Name)` branch retained the base union and rejected subclass fields in the owned binder|V376
B386|2026-07-14|boolean `and` propagated positive None narrowing only while evaluating the condition and not into the true branch, so nested optional fields guarded by the owned binder remained optional inside the guarded body|V375,V376
B387|2026-07-14|the syntax and binder subset admitted dictionary comprehensions but IR lowering handled only list/generator placeholders, blocking the owned binder's copy of imported function return types|V375,V376
B388|2026-07-14|the object-boxing update made tuple storage inspect `.elements` unconditionally even though dictionary literals also use `IrTuple` with `IrDictType`, regressing native emission of every nonempty dict literal|V368,V375
B389|2026-07-14|binder inference typed every `and`/`or` expression as `bool`, so `optional_dict or {}` corrupted the inferred record field layout even though Python boolean operators return an operand value|V375,V376
B390|2026-07-14|tuple assignment required the number of static tuple type entries to equal the target arity, so homogeneous variable-length tuples could neither preserve element types nor reach native unpacking in the owned annotation checker|V375,V376
B391|2026-07-14|global literal collection covered string containers but not read-only literal maps, so `_WIDTH_ALIASES.get(...)` was typed from an unrelated fallback and had no native value in the owned type module|V368,V376
B392|2026-07-14|exact `type(value) is T` comparison reached native tags but did not narrow `value` in the true branch, so the owned binder could not store a guarded AST constant into its typed integer map|V375,V376
B393|2026-07-14|identity comparison sent a tagged `object` and native `bool` through raw pointer comparison, so owned AST checks such as `constant.value is True` could not preserve the bool singleton or distinguish integer `1`|V368,V376
B394|2026-07-14|LLVM `for` emission recognized only the one-entry variadic tuple encoding as homogeneous, diverging from lowerer's equal-element rule and decoding ordinary `(1, 2)` slots as tagged objects after B383|V368,V375,V376
B395|2026-07-14|the first NoReturn-aware lowerer guard used an assignment expression even though assignment expressions are outside the frozen bootstrap subset, so the owned parser could not admit the lowerer itself|V374,V376
B396|2026-07-14|typed dictionaries supported item assignment, lookup, and iteration but not `dict.update`, blocking the lowerer and emitter's ordinary map merges before their native roots could be emitted|V368,V375,V376
B397|2026-07-14|typed dictionaries had no mutating `pop(key, default)` path, so the lowerer's ordinary removal of shadowed global container constants stopped native reachability|V368,V375,V376
B398|2026-07-14|record construction used positional field order whenever any stored field was not a direct `__init__` parameter, misaligning valid constructors that ignore parameters or normalize optional containers before storing them|V368,V376
B399|2026-07-14|statement lowering accepted annotated assignments only for local names and rejected ordinary `self.field: T = value` assignments used by AOT compiler constructors|V374,V375,V376
B400|2026-07-14|cross-module type aliases were collected for annotation parsing but `_aot_type_to_ir_type` did not expand them, so lowerer methods returning the ordinary `IrType` union alias were rejected as unknown types|V374,V376
B401|2026-07-14|local assignment inference merged numeric and string binary operations but not tuple concatenation, so an unannotated concat inherited the enclosing function return type and its loop elements became opaque objects|V368,V375,V376
B402|2026-07-14|ordinary PEP 604 unions used as the second argument to `isinstance` reached generic integer bitwise-or lowering instead of the native type-marker path, blocking union checks in the lowerer itself|V374,V376
B403|2026-07-14|the accepted statically resolved call subset omitted `sorted` over tuple/dict-backed values, including a static key and reverse order, so deterministic AOT compiler ordering stopped native lowerer reachability|V368,V375,V376
B404|2026-07-14|the first native `sorted` oracle compared CPython's list result with tuple literals, so its reference branch reported a false semantic failure before native execution|V379,V384
B405|2026-07-14|None-guard fallthrough refinement recognized function exits but not `continue`, so a loop path after `if value is None: continue` retained the optional record and rejected valid field access|V375,V376
B406|2026-07-14|the first optional-record `continue` oracle instantiated an annotated plain class as though it were a dataclass, so CPython correctly rejected the fixture before the narrowing check|V379,V384
B407|2026-07-14|attribute lowering resolved a union receiver to the sole property method found across its variants, calling that property for variants that instead stored a field; unions with multiple property implementations were rejected outright|V368,V375,V376
B408|2026-07-14|`any`/`all` generator lowering accepted only a name target and did not reuse supported fixed-arity `for` unpacking, rejecting ordinary pair predicates in the lowerer itself|V375,V376
B409|2026-07-14|the first lowerer-root reachability gate asserted a nonexistent `_Lowerer.lower` method instead of the real `lower_function` and `lower_record` call edges|V376,V384
B410|2026-07-14|list/generator comprehensions were lowered to empty placeholder calls, and set comprehensions were not lowered, so their value/filter semantics and nested compiler call edges were absent from native IR|V375,V376
B411|2026-07-14|record method/property resolution checked only the concrete class and not its declared base chain, so inherited AST location properties disappeared from concrete and union receivers in the lowerer|V368,V375,V376
B412|2026-07-14|annotation conversion expanded only exact aliases and left aliases nested inside a union opaque, so `Alias | None` could not be narrowed to one of the alias's concrete record variants|V374,V375,V376
B413|2026-07-14|nonempty dict literals required an enclosing `dict[K, V]` expected type even when all key/value types were statically inferable, rejecting ordinary inline literals such as `{...}.get(key)` in the lowerer|V368,V375,V376
B414|2026-07-14|typed dict lowering implemented only one-argument `get` and always initialized misses with a type default, rejecting and semantically omitting Python's explicit `get(key, default)` form|V368,V375,V376
B415|2026-07-14|bitwise set/frozenset union, intersection, and symmetric difference were routed through integer operators, so typed recursion guards and native set value semantics could not be lowered|V368,V375,V376
B416|2026-07-14|local expression inference had no list/set/tuple literal case, so an unannotated set union inherited the enclosing return fallback even after typed set operators were implemented|V375,V376
B417|2026-07-14|enumerate target binding and emitted target-slot parsing handled only flat tuple unpacking, rejecting nested fixed-arity targets used inside a dict comprehension|V375,V376
B418|2026-07-14|comprehension emission treated lowered `__enumerate` as an unresolved external call because enumerate item/start handling existed only inside statement `for` emission|V375,V376
B419|2026-07-14|the native string subset implemented lowercase conversion and uppercase predicates but omitted ordinary `str.upper`, blocking class-name normalization in the lowerer|V368,V376
B420|2026-07-14|positive `is not None` refinement unwrapped optional records and strings but not optional-bool attributes, so `AotType.signed: bool | None` remained record-typed when the lowerer constructed `IrIntType.signed: bool`|V375,V376
B421|2026-07-14|storing a concrete bool into an optional-bool field reused raw pointer boxing, encoding `False` as null and collapsing it with `None` instead of preserving the native three-state optional-bool representation|V368,V375,V376
B422|2026-07-14|field emission loaded a positively narrowed optional-bool attribute directly as `i1` from its declared pointer slot, interpreting the native `False` tag as true instead of decoding the three-state representation|V368,V375,V376
B423|2026-07-14|binder `__init__` field inference handled homogeneous list literals but not comprehension values or imported-record attributes, so `_Emitter.functions` and related native call-graph state disappeared before emitter-root lowering|V375,V376
B424|2026-07-14|local conditional-expression inference did not merge an empty tuple-backed container arm with a typed nonempty arm, so `_Emitter._emit_fallible_main` inferred `[] if ... else [str]` from its enclosing string return fallback and rejected `append`|V375,V376
B425|2026-07-14|fallthrough narrowing handled `if not isinstance(x, T): exit` but not the complementary `if isinstance(x, T): exit` form, leaving the emitter's `_HandlerScope | _FinallyScope` value ambiguous before a `_FinallyScope.body` access|V375,V376
B426|2026-07-14|binder type-alias collection required the literal first character to be uppercase, so ordinary private aliases such as `_FailureScope = _HandlerScope | _FinallyScope` were left as opaque record names and could not participate in union narrowing|V374,V375,V376
B427|2026-07-14|statement lowering applied positive `isinstance` refinement only to the `if` body and did not apply the complementary type to its `else`/`elif` branch, so emitter code distinguishing `IrDictType` from `IrTupleType` could not access tuple fields|V375,V376
B428|2026-07-14|false-branch `isinstance` refinement leaked past an `if`/`elif` chain even when both true and false paths continued, replacing the original union with the final complement and corrupting later emitter type dispatch|V375,V376
B429|2026-07-14|native lowering implemented only the two-positional-argument integer form of `min`/`max`, rejecting the ordinary nonempty iterable/generator reduction used to size dynamic record allocations in the emitter|V375,V376
B430|2026-07-14|sequence/set comprehension lowering required exactly one generator, rejecting ordinary nested `for` clauses such as the emitter's flattened builtin-tag set and preventing their nested-loop value semantics from reaching native code|V375,V376
B431|2026-07-14|global literal-container collection accepted nested integer literals but not references to earlier scalar constants, so the emitter's `_OBJECT_BUILTIN_TAGS` map had no native value and its ordinary `dict.get` call became unreachable|V368,V376
B432|2026-07-14|nested global tuple literals were always assigned fixed-arity types, so dictionary values containing homogeneous tuples of different lengths were deemed heterogeneous and the emitter's builtin-tag map was discarded|V368,V375,V376
B433|2026-07-14|mutating `update` dispatch handled typed dictionaries but not tuple-backed sets, so the emitter could not accumulate descendant record IDs even though native set union/value deduplication already existed|V368,V375,V376
B434|2026-07-14|generic builtin-call lowering propagated `bool(...)`'s enclosing result type into its operand, so truth-testing a set intersection in an optional-bool function tried to lower the set operation as an integer/record result|V368,V375,V376
B435|2026-07-14|dictionary comprehension lowering and emission still required exactly one generator after sequence comprehensions gained nested loops, rejecting the emitter's ordinary two-clause loop-carried-value map|V375,V376
B436|2026-07-14|one-argument tuple-backed container constructors lowered by forwarding their iterable but local inference discarded that iterable's element type, so `frozenset(values) & names` in fallibility analysis was misrouted to integer bitwise lowering|V375,V376
B437|2026-07-14|binary lowering allowed an inferred integer result to override the enclosing expected type but not an inferred tuple-backed set result, so set operations under `len(...)` or a truth-test retained empty-tuple/bool context instead of their operand element type|V368,V375,V376
B438|2026-07-14|tuple-literal inference treated a starred iterable as one opaque element instead of merging its item type, so a homogeneous fixed prefix plus dynamic suffix became an object-valued fixed tuple and lost record fields during iteration|V368,V375,V376
B439|2026-07-14|`any`/`all` generator lowering and emission encoded exactly one generator pair, rejecting nested generator clauses used by fallibility analysis even though nested comprehension loops were otherwise native-reachable|V368,V375,V376
B440|2026-07-14|rooted slice discovery traversed record-constructor arguments but omitted the constructed class's `__init__` method, so `emit_llvm_text` reached `_Emitter.emit` while silently pruning initialization and its fallibility-analysis edge|V376,V384
B441|2026-07-14|lowering preserved arbitrary positional iterables accepted by `zip`, but LLVM emission hard-coded exactly two inputs, rejecting ordinary three-way strict zips in the emitter itself|V368,V375,V376
B442|2026-07-14|tuple repetition lowering required an enclosing tuple expected type while unannotated assignment inference recognized only numeric multiplication, so compiler locals such as `types * len(targets)` inherited a `None` function fallback and emitted invalid `mul void`|V368,V375,V376
B443|2026-07-14|record construction mapped explicit `__init__` parameters directly into stored fields and defaulted every computed field without executing the initializer, so native `_Emitter(module)` had empty function/record/fallibility tables despite an apparently reachable `__init__` symbol|V368,V376,V380,V384
B444|2026-07-14|global literal-map collection normalized nonempty homogeneous nested tuples but could not merge an empty tuple with the same variadic item type from sibling values, dropping the emitter's LLVM C-API signature table and misresolving `.get` as an optional-record method|V368,V375,V376
B445|2026-07-14|global tuple-backed constant collection ignored one-argument `frozenset`/`set` constructors and starred references to earlier global containers, so the emitter's builtin-value marker set became an opaque null membership operand|V368,V375,V376
B446|2026-07-14|annotation conversion collapsed only optional tuple-backed unions and left ABI-equivalent unions such as `tuple[T, ...] | list[T]` opaque, so loop unpacking erased nested dictionary values before method dispatch|V368,V375,V376
B447|2026-07-14|zero-argument `super()` calls were admitted as generic externals, emitting unresolved `super` and `super().__init__` symbols instead of statically dispatching project bases or honoring the native status/error boundary for builtin exception bases|V368,V375,V376,V380
B448|2026-07-14|LLVM branch-name merging propagated a local assigned on only one of multiple fallthrough paths, later forming dead phis whose incoming values did not dominate the advertised predecessor block|V375,V376,V384
B449|2026-07-14|lowerer used `NoReturn` annotations for guard refinement but emitted ordinary project calls, so status-aware LLVM still created a reachable success continuation after functions such as `_Emitter._error` and polluted definite-assignment/phi control flow|V367,V375,V376,V380
B450|2026-07-14|the native `xcc.aot.cli` contract stopped after option validation and never opened source, ran the owned compile pipeline, wrote LLVM, or invoked the allowed native tools|V372,V376,V378
B451|2026-07-14|an independently compiled Python entry named `main` and its generated C process wrapper were both emitted as `@main`, producing an invalid duplicate LLVM definition|V376,V384
B452|2026-07-14|generic LLVM functions emitted a source parameter named `%entry` in the same local namespace as the mandatory `entry:` basic block label, making an otherwise valid native CLI function unparsable by `llc`|V376,V384
B453|2026-07-14|local expression inference recognized tuple repetition but not ordinary string/bytes repetition, so a parser comparison such as `text[slice] == quote * 3` emitted an invalid pointer multiplication|V368,V375,V376
B454|2026-07-14|native lowering implemented `ord` as an integer intrinsic but assignment inference left its result opaque, so integer arithmetic inside a conditional expression mixed pointer and integer values in the owned parser|V368,V375,V376
B455|2026-07-14|the subset reachability artifact explicitly reported `native_call_graph=false` and listed only module imports, so it had no reason edges proving the CLI-to-parser/binder/lowerer/emitter closure|V376,V383,V384
B456|2026-07-14|the native compile pipeline passed freshly lowered IR directly to LLVM emission without an explicit symbol-table validator, allowing duplicate definitions or a missing entry to fail only in downstream tools|V376,V384
B457|2026-07-14|cross-module method resolution saw both a short import alias and the canonical project symbol for inherited AST properties, deemed the suffix ambiguous, and emitted an undefined bare `AST.col_offset` call|V375,V376
B458|2026-07-14|binary lowering applied string/bytes/float special cases before inferred operand types could override an enclosing opaque object-field context, leaving narrowed string concatenation as an unresolved generic `__add` call|V368,V375,V376
B459|2026-07-14|boxing a nullable record union as opaque `object` allocated a record-tag wrapper even when the source value was `None`, so native `isinstance` dereferenced a null record payload and crashed the owned parser's `_children` helper|V368,V375,V376,V384
B460|2026-07-14|fallthrough branch merging overwrote an incoming nullable record type with the concrete type assigned only on one branch, so later object boxing again treated the joined null pointer as a non-nullable record|V368,V375,V376,V384
B461|2026-07-14|the first B460 join repair restored every divergent incoming type, preserving an optional set after its assignment chain and sending the emitter's own set intersection through integer binary lowering in the complete CLI root|V375,V376,V384
B462|2026-07-14|global tuples of `ast.<Type>` markers were not collected for `isinstance`, so `_UNSUPPORTED_NODES` remained one opaque marker and native lowering reduced `isinstance(node, _UNSUPPORTED_NODES)` to `node is not None`|V374,V375,V376,V384
B463|2026-07-14|the first B462 collector also admitted dictionaries whose values were `ast.<Type>` constructors, shadowing the dedicated record-constructor map and turning the parser's `operator_type()` dispatch into an unsupported dynamic call|V375,V376,V384
B464|2026-07-14|the sliced record walker ignored `isinstance` marker names because their IR values had opaque `object` type, so all 12 expanded unsupported-node records were omitted and LLVM again reduced the check to pointer non-nullness|V376,V383,V384
B465|2026-07-14|LLVM emitted both conditional-expression arms eagerly and selected only after evaluation, so the binder's unselected `owner + '.' + name` arm called `strlen(NULL)` when `owner` was `None`|V368,V375,V376,V384
B466|2026-07-14|three emitter regressions encoded the old eager-ifexp `select` shape, so they rejected the required lazy branch/phi CFG even after CPython/native behavior matched|V379,V384
B467|2026-07-14|local container inference had no `JoinedStr` case, so an unannotated list initialized with an f-string stored its first element as a tagged opaque object instead of a native string|V368,V375,V376
B468|2026-07-14|tuple-backed list/set/dict mutations returned a replacement allocation and rebound only the callee local, so `.append()` and related mutations were invisible to callers that held the original Python container object|V368,V375,V376,V384
B469|2026-07-14|subscript-assignment item inference recognized tuple-backed sequences but not `IrDictType`, so a direct integer value in `dict[str, int]` assignment inherited the enclosing `None` return fallback and was rejected|V375,V376
B470|2026-07-15|named-slice class discovery kept the first deterministic module owner for a short class name but the refinement pass unconditionally replaced its metadata with a later same-named class, so the hosted `xcc.aot.cli` source closure paired `xcc.aot.py_ast.FunctionDef` ownership with `xcc.ast.FunctionDef` fields and rejected `statement.args`|V376,V383,V384
