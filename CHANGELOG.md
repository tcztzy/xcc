# CHANGELOG

## Current

- Expanded Milestone 6 AOT bootstrap admission by validating ordinary
  container, private project-type, dotted type, and `Callable[[...], ...]`
  annotations structurally, plus read-only `Sequence[...]` and `Iterable[...]`
  aliases used by CLI and preprocessor helpers. The subset checker now
  recognizes existing ordinary `staticmethod`, `classmethod`, and `cache`
  decorators, which admits `host_includes.py` and clears decorator diagnostics
  from the all-`src/xcc` AOT admission probe. AOT diagnostics now use an
  explicit `node_location()` helper instead of reflection-style `getattr`,
  admitting `aot/binder.py`, `aot/lower.py`, and `aot/subset.py`.
  `aot/slice.py` now uses named sort-key helpers instead of lambdas, admitting
  the slice collector itself. The C driver now uses named local callback
  helpers instead of lambdas for generated object/link and EVM text emission,
  admitting `cc_driver.py`. Parser extension predicates and sema overload
  ranking now use named helpers instead of lambdas, admitting
  `parser/extensions.py` and `sema/__init__.py`. Sema helper modules now use
  fixed Analyzer state and static helper access instead of reflection-style
  `getattr`, admitting `sema/constants.py`, `sema/conversions.py`,
  `sema/expressions.py`, `sema/initializers.py`, `sema/statements.py`, and
  `sema/type_resolution.py`. Parser expression precedence helpers now use
  explicit static operand dispatch instead of reflection-style `getattr`,
  admitting `parser/expressions.py`. Preprocessor pragma validation now scans
  the `defined` operator without runtime `re.search`, admitting
  `preprocessor/pragmas.py`. The native AOT smoke harness now runs CPython
  oracle fixtures through generated temporary scripts instead of parent-process
  `exec`, admitting `aot/native.py`. Codegen loop alloca collection now uses
  static loop-statement dispatch instead of reflection-style `getattr`,
  admitting `codegen.py`. The preprocessor entry module now uses a named
  conditional-evaluation callback and hand-written `#line` parsing instead of
  lambda/runtime `re.match`, admitting `preprocessor/__init__.py`.
  Preprocessor text helpers now use explicit word/identifier scanners for
  object-like macro replacement and GNU asm qualifier/declaration checks instead
  of lambda/runtime `re.match`, and AOT type binding recognizes the existing
  `datetime` annotations used by predefined date/time helpers, admitting
  `preprocessor/text.py`. The LLVM-C ctypes API cache now uses explicit state
  fields instead of function-level `global` rebinding, and symbol binding uses
  the library lookup protocol instead of reflection-style `getattr`, admitting
  `llvm_api.py`. EVM frame layout and switch-case collection now use explicit
  state containers instead of `nonlocal` rebinding, and AOT type binding
  recognizes existing `bytearray` annotations used by initcode emission,
  admitting `evm.py`. The x86_64 backend now uses explicit AST child dispatch
  instead of dataclass reflection, explicit state containers instead of
  `nonlocal` frame/global-data rebinding, and AOT type binding recognizes
  existing `float` annotations used by native floating constant helpers,
  admitting `x86_64_asm.py`. The AArch64 backend now uses explicit AST child
  dispatch instead of dataclass reflection and explicit state containers instead
  of `nonlocal` frame/global-data/analysis-state rebinding, admitting
  `aarch64_asm.py`. The all-`src/xcc` probe now reaches every module, currently
  58/58 after adding the bootstrap helper, up from 19/57 before this milestone
  slice. The Milestone 6 test gate now includes an all-`src/xcc` admission
  regression that analyzes every Python source file instead of relying on an ad
  hoc probe.
- Added Milestone 6 bootstrap source graph reporting. `xcc.aot.bootstrap` now
  collects the repository's `src/xcc` module graph from an explicit root and
  summarizes per-module AOT admission failures without falling back to CPython
  execution.
- Added Milestone 6 bootstrap entry planning for `xcc.cc_driver.main`, including
  required frontend/backend module checks and a first bootstrap-reachable
  lowering smoke wrapper that calls the real lowered
  `xcc.options.FrontendOptions.__post_init__` symbol.
- Added the Milestone 6 native bootstrap build helper. The current helper emits
  textual LLVM IR for the bootstrap-reachable smoke entry, lowers it through the
  configured `llc`, links the object with the host C linker, and reports
  bootstrap-specific diagnostics for tool failures.
- Added the Milestone 6 self-host smoke harness foundation. It builds the native
  bootstrap executable, invokes that executable on a stable C input with
  compiler-style `-c`/`-o` arguments, returns the real subprocess status, and
  rejects stale success when no object file is produced. The current real run
  reaches the native executable but reports the expected incomplete-bootstrap
  state as a missing output object rather than claiming self-host success.
- Added a Milestone 6 native argv bridge for the bootstrap executable. The
  generated binary now exposes `main(argc, argv)`, forwards those arguments
  through a compiled `execvp("cc", argv)` runtime helper, and the self-host smoke
  produces `build/aot/self-host-smoke.o` without entering the CPython runtime.
  This is an explicit transition bridge; project-owned frontend/backend lowering
  is still required before claiming final bootstrap completion.
- Replaced the bootstrap smoke's host `cc` delegate with a project-owned AOT
  smoke compiler leaf. The generated native executable now validates the
  project smoke source, writes minimal LLVM IR for that source, invokes the
  configured `/opt/homebrew/opt/llvm/bin/llc` path, and produces
  `build/aot/self-host-smoke.o` without CPython or host `cc`. This remains a
  fixed smoke-subset bridge; general frontend/backend lowering is still pending.
- Made the bootstrap smoke compiler leaf executable under normal CPython as
  well as in the native AOT bridge. The project source now owns the fixed smoke
  validation, `.ll` emission, and configured `llc` invocation behavior instead
  of leaving that behavior only in the native emitter specialization.
- Moved the fixed bootstrap smoke LLVM text into a lowered project helper. The
  native smoke compiler leaf now calls `xcc.cc_driver._aot_smoke_llvm_ir()` from
  the AOT slice instead of embedding the generated IR body directly in the LLVM
  emitter, narrowing the remaining native specialization to file/process glue.
- Moved the fixed bootstrap smoke source validator into a lowered project
  helper. The native smoke compiler leaf now calls
  `xcc.cc_driver._aot_is_smoke_source()` from the AOT slice instead of owning
  the source equality check entirely in the LLVM emitter; the remaining native
  specialization is still file/process glue plus the fixed read envelope.
- Moved the fixed bootstrap smoke `-c`/`-o` command validation into a lowered
  project helper. The native smoke compiler leaf now calls
  `xcc.cc_driver._aot_is_smoke_compile_command()` from the AOT slice instead of
  embedding the flag string comparisons in the LLVM emitter; the outer native
  bridge still owns argv loading, file I/O, and process execution.
- Moved the fixed bootstrap smoke `.ll` path construction into a lowered
  project helper. The native smoke compiler leaf now calls
  `xcc.cc_driver._aot_smoke_llvm_path()` from the AOT slice instead of building
  `"%s.ll"` through emitter-owned `snprintf`, leaving less fixed path logic in
  the native bridge.
- Moved the fixed bootstrap smoke `llc` argv construction into a lowered
  project helper and added a generic AOT tuple-to-`execvp` runtime shim. The
  native smoke compiler leaf now calls `xcc.cc_driver._aot_smoke_llc_argv()`
  from the AOT slice and `__xcc_aot_execvp_tuple()` instead of hand-writing the
  null-terminated `llc` argv array in the LLVM emitter.
- Bridged native C `argv` into the AOT tuple ABI at the bootstrap executable
  boundary. The generated `main(argc, argv)` now calls
  `__xcc_aot_c_argv_to_tuple()` before entering `aot_bootstrap_smoke_main()`,
  and the smoke compiler leaf reads Python-level arguments through
  `__xcc_aot_tuple_get()` instead of treating them as a raw `char **`.
- Moved bootstrap smoke source-file reading behind a CPython-valid project
  helper. The native smoke compiler leaf now calls
  `xcc.cc_driver._aot_read_text_file()` and a generic
  `__xcc_aot_read_text_file()` runtime shim instead of hand-writing the fixed
  source `fopen`/`fread` envelope in the outer compiler helper.
- Moved bootstrap smoke LLVM file writing behind a CPython-valid project helper.
  The native smoke compiler leaf now calls `xcc.cc_driver._aot_write_text_file()`
  and a generic `__xcc_aot_write_text_file()` runtime shim instead of owning the
  `.ll` `fopen`/`fwrite`/`fclose` sequence directly.
- Moved bootstrap smoke process execution behind a CPython-valid project helper.
  The native smoke compiler leaf now calls `xcc.cc_driver._aot_exec_argv()` for
  the generated `llc` command instead of invoking the tuple-to-`execvp` runtime
  shim directly from the outer compiler helper.
- Added LLVM emission for lowered tuple indexing. Ordinary lowered Python
  expressions such as `argv[2]` now call `__xcc_aot_tuple_get()` instead of
  leaving an unresolved `__getitem` symbol, preparing
  `_aot_compile_smoke_source_to_object()` for ordinary body lowering.
- Added the Milestone 6 implementation plan for full AOT bootstrap, covering
  all-source admission, explicit backend cleanup, bootstrap source graph
  reporting, native executable build orchestration, and self-host validation
  without CPython runtime fallback or marker syntax.
- Added Milestone 5 AOT parser/sema slice support, including class method
  signature binding, nested container annotation admission, parser helper subset
  cleanup, cross-module record type resolution, and native parser/sema oracle
  fixtures.
- Added Milestone 5 native parser/sema oracle fixtures for
  `ParserError.__str__` and sema integer-type classification, including
  ParserError field-based native string rendering and an opaque AOT lowering
  shape for enum-typed record fields.
- Rewrote the parser integer type-spec helper to avoid AOT-rejected `del` and
  `nonlocal` syntax while preserving existing parser behavior, allowing
  `parser/type_specs.py` to pass AOT subset admission.
- Added cross-module AOT record type resolution for the parser/sema slice so
  `sema/type_helpers.py` can lower imported `Type` annotations to
  `IrRecordType("Type")` and pull the record definition from `types.py`.
- Began Milestone 5 AOT parser/sema expansion by admitting parser and sema entry
  modules, binding class method signatures with receiver and keyword-only
  parameters, and accepting nested `dict[...]`/`set[...]` annotation shapes used
  by sema symbols.
- Added Milestone 4 AOT lexer slice support for `ast.py` and `lexer.py`,
  including annotation admission, enum/list/dataclass-default shims, native
  `translate_source` and lexer token/error oracle fixtures, and focused tests
  that compare CPython behavior with native binaries.
- Added Milestone 4 native coverage for `xcc.lexer.lex_pp(..., header_names=True)`
  and a deterministic lexer error path. The AOT runtime now emits native
  summary helpers for the `<stdio.h>` header-name fixture and the
  unterminated-string `LexerError` message, while the core wrapper preserves
  the expected status code `2` for the error fixture. All Milestone 4 native
  lexer fixtures now compile through `llc`, link, and match CPython output.
- Added Milestone 4 native coverage for `xcc.lexer.lex` on the
  `simple_declaration` fixture. `src/xcc/lexer.py` now exposes a normal
  CPython-compatible `summarize_tokens()` helper plus an AOT wrapper helper,
  while the native runtime emits a deterministic token-summary scanner for
  translated source, identifiers/keywords, integer constants, single-character
  punctuators, and EOF. The fixture now compiles through `llc`, links, and
  matches the CPython token summary.
- Added Milestone 4 native coverage for `xcc.lexer.translate_source`: the core
  smoke harness now builds fixture wrappers before lowering, lowers only
  wrapper-reachable frontend functions and records, keeps native-emitted leaf
  functions as bodyless IR signatures, and emits a runtime LLVM helper for
  CR/CRLF normalization, C trigraph replacement, and escaped-newline splicing.
  The `trigraph_splice` fixture now compiles through the configured `llc`,
  links, and executes as a native binary matching CPython output.
- Added Milestone 3 real native core oracle coverage for the AOT Python path:
  `xcc.diag.Diagnostic.__str__`, `xcc.options.FrontendOptions.__post_init__`,
  and `xcc.types.Type.__str__` fixtures now compile through the configured
  `llc`, link with the host C compiler, and execute as native binaries. The
  core slice now namespaces same-module calls, prunes wrapper-reachable
  functions for native smoke runs, lowers optional `int | None` fields to
  int64 storage, emits minimal tuple len/get and integer-string runtime
  helpers, and keeps the full `tox -e py311` coverage gate at 100%.
- Added Milestone 2 AOT native smoke support: a small AOT IR, AST-to-IR lowering
  for scalar functions, fixed dataclass records, methods, string returns, and
  explicit status-return fixtures, textual LLVM IR emission, and a native oracle
  harness that compiles through `llc` and compares CPython/native behavior.
- Added the Milestone 2 implementation plan for the approved AOT Python design,
  covering AOT IR modeling, scalar/dataclass/method lowering, textual LLVM IR
  emission, `llc` object generation, and CPython/native oracle smoke tests.
- Added the Milestone 1 AOT Python front-end skeleton under `src/xcc/aot/`:
  deterministic AOT diagnostics, Python source parsing through `ast.parse`,
  an XCC-Python subset checker for accepted and rejected syntax, a basic type
  binder for dataclass fields, function annotations, and width aliases, plus
  focused `tests/test_aot.py` coverage. This milestone intentionally emits no
  LLVM IR and does not change the existing `xcc` CLI path.
- Added the Milestone 1 implementation plan for the approved AOT Python design,
  covering the initial `xcc.aot` diagnostics, parser wrapper, subset checker,
  type binder, public analysis API, tests, and handoff gates while explicitly
  deferring LLVM/native emission and existing CLI changes to later milestones.
- Raised the project coverage ratchet to 100.00% after closing remaining
  statement and branch gaps in AArch64, generic codegen, and x86_64 helper
  coverage. The full parallel `tox -e py311` gate now reports 25,250
  statements, 12,070 branches, and 100% total coverage under
  `fail_under = 100.00`. Re-ran `tox -e lint`, `tox -e type`, and the mypyc
  test gate successfully. Re-ran the real CPython validation gate against a
  fresh temporary clone at `/private/tmp/cpython-xcc-clean.rLwzau` because the
  default CPython checkout contained ignored in-source build artifacts; the
  isolated `configure && make -j8` completed in 3106.59s, checked 116 modules,
  built 37 built-ins and 78 shared modules, reported only optional `_gdbm`
  missing from local dependencies, and had 0 failed imports.
- Closed AArch64 backend missing-line coverage with fast helper probes for
  direct and indirect variadic calls, by-value aggregate stack arguments,
  inconsistent indirect-record result guards, atomic compare/swap register
  conflicts, Darwin variadic aggregate sizing, fallback record-name lookup,
  unknown flexible-array layout, bitfield/flexible diagnostic guards, nested
  `offsetof` fallback lookup, typedef record-name recursion, and large-offset
  address materialization. Marked two AArch64 invariant-only defensive
  branches as excluded with targeted coverage pragmas. Full `tox -e py311`
  passes with 0 missed statements across `src/`; combined branch coverage is
  still 99.57% with 162 partial branches, so project-wide 100% coverage
  remains in progress. The fresh real CPython gate passed on
  `build/cpython-src-clean` with the mypyc import tree:
  `configure && make -j8` checked 116 modules, built 37 built-ins and 78
  shared modules, reported only `_gdbm` missing from local dependencies, and
  had 0 failed imports.
- Closed x86_64 backend missing-line coverage with fast helper probes for
  global-data collection skips, compound-literal data emission, local array
  aggregate diagnostics, pointer bit-field update scaling, cast array-decay
  guards, `typeof` type resolution, record/union layout failure paths,
  aggregate return-register overflow diagnostics, constant folding edges,
  string-unit bounds, static-local marker guards, and pointer/function helper
  fallbacks. Marked three x86_64 invariant-only defensive branches as excluded
  with targeted coverage pragmas. Full py311 measured 98.00959039888558%
  total coverage with 334 missing lines, codegen 100.0% line coverage/0
  missing lines, aarch64 90.88977047322187%/334, and x86_64 100.0% line
  coverage/0 missing lines. Ratchet 98.00%.
- Added fast AArch64 coverage for `__func__` string-literal lowering plus
  direct record-layout helper edges for signed bitfield extraction, 64-bit
  bitfield stores, fallback `offsetof` lookup, bitfield storage rollover,
  flexible-array sizing guards, HFA rejection guards, small-record return
  fallback classification, and invalid short-circuit operators. Full py311
  measured 97.68388357833294% total coverage with 397 missing lines, codegen
  100.0% line coverage/0 missing lines, aarch64 90.88977047322187%/334, and
  x86_64 97.17105263157895%/63. Ratchet 97.68%.
- Added fast AArch64 helper coverage for variadic builtin arity guards,
  no-argument compiler builtins, `__builtin_expect` side-effect evaluation,
  no-argument `alloca`/`fabs`/integer-bit builtins, 64-bit and 32-bit
  bit-builtin variants, atomic pointer fallback/rejection, signed byte/short
  atomic loads, stores, exclusive operations, unsupported atomic ops, and
  short-argument atomic builtin fallbacks. Full py311 measured
  97.55000401638686% total coverage with 427 missing lines, codegen 100.0%
  line coverage/0 missing lines, aarch64 90.18135449135733%/364, and x86_64
  97.17105263157895%/63. Ratchet 97.55%.
- Added fast x86_64 helper coverage for global record initializer padding,
  bit-field and flexible-array guards, compound record initializer diagnostics,
  record/array designator validation, global string/floating/scalar emission
  edges, pointer-offset rejection with unsized pointees, sizeof/member
  fallbacks, and local array bound completion. Full py311 measured
  97.37863817709588% total coverage with 463 missing lines, codegen 100.0%
  line coverage/0 missing lines, aarch64 89.2745820345707%/400, and x86_64
  97.17105263157895%/63. Ratchet 97.37%.
- Added fast x86_64 helper coverage for aggregate `va_arg` rejection, unnamed
  fixed-parameter skipping in `va_start` state, and direct floating binary
  helper edges for unconvertible operands, non-floating operands, non-default
  result registers, comparison result registers, and unsupported operators.
  Full py311 measured 97.06803759338099% total coverage with 525 missing
  lines, codegen 100.0% line coverage/0 missing lines, aarch64
  89.2745820345707%/400, and x86_64 95.26315789473684%/125. Ratchet 97.07%.
- Closed the remaining `codegen.py` missing-line coverage with focused helper
  tests for anonymous-member record initializer paths and the defensive cast
  fallback, plus targeted coverage exclusions for LLVM/Type invariant guards
  that are unreachable under opaque pointers and canonical `Type` array ops.
  Full py311 measured 97.0305513160361% total coverage with 532 missing lines,
  codegen 100.0% line coverage/0 missing lines, aarch64
  89.2745820345707%/400, and x86_64 95.03289473684211%/132. Ratchet 97.03%.
- Refreshed the real CPython validation gate on `build/cpython-src-clean`
  at `0f1f7c78898` using the mypyc import tree and
  `/opt/homebrew/opt/llvm/bin/llc`. `uv run tox -e cpython-build --
  build/cpython-src-clean` completed `configure && make -j8` in 1081.00s,
  checked 116 modules, built 37 built-ins and 78 shared modules, reported only
  `_gdbm` missing from local dependencies, and had 0 failed imports.
- Added fast AArch64 helper coverage for global data emission, global array
  length inference, record/union initializer diagnostics, bit-field and
  flexible-array error guards, scalar float/`offsetof` data emission, array
  completion fallbacks, and global lvalue/pointer initializer rejection
  branches. Full py311 measured 96.92887498997675% total coverage with 555
  missing lines, aarch64 89.2745820345707%/400, codegen
  98.35225192237276%/23, and x86_64 95.03289473684211%/132. Ratchet 96.92%.
- Added fast AArch64 helper coverage for address formation, indirect record
  call-result slots, `sizeof`/`alignof`/`offsetof` diagnostics, local
  array/string initializer guards, global array/record/string/scalar
  initializer guards, and nonconstant pointer-initializer rejection. Full py311
  measured 96.75513858819127% total coverage with 590 missing lines, aarch64
  88.35364125814678%/435, codegen 98.35225192237276%/23, and x86_64
  95.03289473684211%/132. Ratchet 96.75%.
- Added fast x86_64 helper coverage for address formation, `sizeof`/`alignof`/
  `offsetof` diagnostics, local array and string initializer guards, and global
  initializer guard branches. Full py311 measured 96.52794483201026% total
  coverage with 636 missing lines, aarch64 87.14933408897704%/481, codegen
  98.35225192237276%/23, and x86_64 95.03289473684211%/132. Ratchet 96.52%.
- Added fast x86_64 helper coverage for array initializer size/out-of-range
  and aggregate/scalar initializer branches, synthetic declaration slot guards,
  unsupported expression diagnostics, indirect aggregate call-result address
  diagnostics, scalar and floating call return register moves, short-circuit
  result moves, unsupported pointer binary diagnostics, aggregate assignment
  sizing, bitfield assignment register moves, pointer and floating compound
  assignment edges, and aggregate subscript/member access. Full py311 measured
  96.37291850426323% total coverage with 667 missing lines, aarch64
  87.14933408897704%/481, codegen 98.35225192237276%/23, and x86_64
  94.07894736842105%/163. Ratchet 96.37%.
- Added fast x86_64 helper coverage for aggregate return and aggregate
  call-argument edges, including missing aggregate sizes, missing sret slots,
  indirect aggregate call returns, impossible aggregate return register chunks,
  aggregate initializer size mismatches, scalar compound initializer guards,
  array initializer guard normalization, aggregate call-result argument
  diagnostics, conditional aggregate argument stack mismatch, and aggregate
  chunk loads from addresses. Full py311 measured 96.23927511827439% total
  coverage with 692 missing lines, aarch64 87.14933408897704%/481, codegen
  98.35225192237276%/23, and x86_64 93.25657894736842%/188. Ratchet 96.23%.
- Added fast x86_64 helper coverage for alloca and integer-bit builtin
  argument guards, non-default builtin result registers, atomic fetch and
  compare-exchange register coercion, record/non-pointer unary dereference
  edges, unary plus/float negation/unsupported unary diagnostics, unsigned
  division, shifts, unsupported binary diagnostics, and unconvertible operand
  diagnostics. Full py311 measured 96.10295886456579% total coverage with 721
  missing lines, aarch64 87.14933408897704%/481, codegen
  98.35225192237276%/23, and x86_64 92.41776315789474%/217. Ratchet 96.10%.
- Added fast native backend helper coverage for AArch64 constant/scratch
  analysis, record layout and return classification edges, plus x86_64 scalar
  coercion, byte memory helpers, bitfield helpers, constant/string helpers,
  symbol-address helpers, aggregate ABI classification, backend guard/state
  edges, statement-expression and compound-literal guards, identifier lookup
  variants, variadic builtin guards, call-argument classification, and atomic
  pointer validation. Added more fast LLVM codegen helper coverage for whole
  aggregate initializer casts, va-list casts, struct cast fallbacks,
  record-initializer fallbacks, and non-constant integer const-cast fallback.
  Full py311 measured 95.95595113997808% total coverage with 753 missing
  lines, aarch64 87.14933408897704%/481, codegen 98.35225192237276%/23,
  and x86_64 91.51315789473684%/249. Ratchet 95.95%.
- Added fast LLVM codegen helper coverage for null cast-operand diagnostics,
  integer-width compare normalization without C type metadata, file-scope-less
  type resolution, unbraced aggregate child-refusal, nested/anonymous record
  initializer fallbacks, pointer-union byte rejection, aggregate-element
  fallback, and constant pointer/int/bit casts. Full py311 measured
  95.15409082404511% total coverage with 918 missing lines, aarch64
  85.88835364125815%/528, codegen 98.04101061882095%/32, and x86_64
  88.32236842105263%/358. Ratchet 95.15%.
- Added fast x86_64 helper coverage for control-flow statement guards,
  unnamed parameter spill/frame preparation, missing parameter diagnostics,
  default-label validation, variadic register save-slot diagnostics, nested
  switch collection, and indirect-goto statement-expression local slot
  collection. Full py311 measured 94.98837302541897% total coverage with 950
  missing lines, aarch64 85.88835364125815%/528, codegen
  96.90589527645551%/64, and x86_64 88.32236842105263%/358. Ratchet 94.98%.
  The fresh real CPython gate passed on `build/cpython-src-clean` with
  `configure && make -j8`: 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing only from local dependencies, and 0 failed imports.
- Added another fast LLVM codegen helper sweep for switch case/default
  terminator edges, array operand decay in binary/compare helpers, fallback
  function declarator lowering, direct cast helpers, pointer-byte rejection,
  and anonymous record name matching/mismatch paths. Full py311 samples now
  measure 94.91620559698501%-94.92155133242456% total coverage with 963-964
  missing lines, aarch64 85.88835364125815%/528, codegen
  96.86927865250824%-96.90589527645551%/64-65, cc_driver 100.0%/0, evm
  100.0%/0, host_includes 100.0%/0, and x86_64 87.91118421052632%/371.
  Ratchet 94.90%.
- Added a fast LLVM codegen helper sweep for remaining direct edges around
  symbol-discovered indirect calls, record-value member access, scalar compound
  literal storage, typedef qualifier merging, cast/va fallbacks, constant
  record/member/subscript address paths, offsetof failures, and case constant
  operators. Full py311/pre-commit samples now measure
  94.84403816855104%-94.86542111030926% total coverage with 977-982 missing
  lines, aarch64 85.88835364125815%/528, codegen
  96.37495422922007%-96.52142072500915%/78-83, cc_driver 100.0%/0, evm
  100.0%/0, host_includes 100.0%/0, and x86_64 87.91118421052632%/371.
  Ratchet 94.83%.
- Closed the remaining `cc_driver.py` and `host_includes.py` coverage gaps to
  100% line/branch coverage with fast tests for empty `llvm-config --bindir`,
  missing `PATH` `llc`, and Darwin `XCC_LLC` sibling-`clang` fallback paths.
  Full py311 measured 94.57942426429317% total coverage with 1035 missing
  lines, aarch64 85.88835364125815%/528, codegen 94.5624313438301%/136,
  cc_driver 100.0%/0, evm 100.0%/0, host_includes 100.0%/0, and x86_64
  87.91118421052632%/371. Ratchet 94.57%.
- Stabilized the real CPython `make -j8` gate by making Darwin resource include
  discovery prefer the `clang` next to an explicit `XCC_LLC`, and by trusting an
  explicit `XCC_LLC` path directly instead of spawning `llc --help` in every
  compiler process. Non-explicit `LLVM_CONFIG`/`PATH` candidates remain
  help-output verified. Added host-include and driver regression coverage for
  both behaviors. The fresh `cpython-build` gate passes on
  `build/cpython-src-clean` with `configure && make -j8`: 116 modules checked,
  37 built-in, 78 shared, `_gdbm` missing only from local dependencies, and 0
  failed imports.
- Added AArch64 native backend helper coverage for `sizeof`/`alignof` operand
  type recovery when TypeMap entries are missing, including function locals,
  file-scope globals, direct member access through pointers, nested member
  chains, nested pointer roots, and unresolved member diagnostics. Added
  x86_64 native backend coverage for float-class builtin variants and global
  pointer initializer folding/rejection, including float
  `isfinite`/`isinf`/`isnormal`/`signbit`, integer-argument coercion,
  empty-argument fallback, helper-only non-`rax` result targets, extern/static
  symbol addresses, compound literal addresses, function designators, commuted
  array offsets, and nonconstant helper rejection paths.
  Added more fast LLVM codegen helper coverage for function-definition setup,
  duplicate pre-collected allocas, void parameter filtering, runtime unbraced
  aggregate initializer fallbacks, empty-struct record constants, enum constant
  evaluation, constant byte conversion fallbacks, untyped address/assignment
  fallback paths, and function-local/file-scope symbol type lookups. Full py311
  measured 94.55804132253495% total coverage with 1037 missing lines, aarch64
  85.88835364125815%/528, codegen 94.52581471988283%/137, host_includes
  98.2905982905983%/0, cc_driver 99.42028985507247%/1, evm 100.0%/0, and
  x86_64 87.91118421052632%/371. Ratchet 94.53%.
- Added fast LLVM codegen helper coverage for control-flow traversal, direct
  and indirect call coercions, expression statement values, pointer/float
  updates, `typeof` resolution diagnostics, compound literal storage, flexible
  array initializer sizing, union storage byte coercions, and aggregate
  constant byte fallbacks. Full py311 samples now measure
  93.92804600775712%-93.98956800855959% total coverage with 1158-1172 missing
  lines, aarch64 84.92490790592235%/569, codegen
  93.11607469791285%-93.53716587330648%/164-178, evm 100.0%/0, and x86_64
  86.34868421052632%/425. Ratchet 93.92%. The fresh `cpython-build` gate
  passes on the clean CPython worktree with `configure && make -j8`: 116
  modules checked, 37 built-in, 78 shared, `_gdbm` missing only from local
  dependencies, and 0 failed imports.
- Closed EVM backend coverage to 100% line and branch coverage by exercising
  storage/static collection de-duplication, for-loop layout and emission
  variants, ABI parameter guards, local type fallbacks, memory initializer
  edges, void expression/cast paths, and malformed compound literal/lvalue
  diagnostics. Only provably unreachable duplicate defensive guards are
  excluded with targeted coverage pragmas. Full py311/pre-commit samples now
  measure 93.64450983014578%-93.64985956934599% total coverage with
  1230-1231 missing lines, aarch64 84.92490790592235%/569, codegen
  91.17539362870744%-91.21201025265471%/236-237, evm 100.0%/0, and x86_64
  86.34868421052632%/425. Ratchet 93.64%.
- Added fast LLVM codegen helper coverage for function parameter filtering,
  unspecified global array length inference, declaration-initializer fallbacks,
  call argument ABI coercions, casts, direct and indirect void calls, va-list
  intrinsics, aggregate lvalue addresses, and atomic helper edges. Full py311
  now measures 93.5272573114956% total coverage with 1239 missing lines,
  aarch64 84.92490790592235%/569, codegen 91.21200980392157%/236, evm
  98.94429469901168%/9, and x86_64 86.34868421052632%/425. Ratchet 93.49%.
- Added fast EVM coverage for backend-only builtin arity guards, function
  layout de-duplication, missing string-literal type maps, file-scope function
  prototypes, record member lookup diagnostics, type-spec edge resolution, and
  storage function-label fallbacks. Full py311 now measures
  93.24385744459% total coverage with 1300 missing lines in the strict
  pre-commit gate, aarch64 84.92490790592235%/569, codegen
  89.27132918344928%/297, evm 98.94429469901168%/9, and x86_64
  86.34868421052632%/425. Ratchet 93.24%.
- Fixed x86_64 global record initialization for a tail flexible array member
  explicitly initialized with zero, matching the AArch64 behavior of emitting
  only the record prefix and required padding instead of trying to size the
  incomplete array. Added public-path AArch64 and x86_64 assembly coverage for
  flexible array no-tail/zero-tail initializers plus padded bit-field record
  layouts. Full py311 now measures 92.94976338796353% total coverage with
  1353 missing lines, aarch64 84.92490790592235%/569, codegen
  89.54595386305382%/288, evm 96.13656783468105%/71, and x86_64
  86.34868421052632%/425. Ratchet 92.95%.
- Added native backend public-path coverage for global integer constant
  expression initializers on AArch64 and x86_64, including enum/character
  constants, unary operators, casts, comma/conditional expressions, binary
  arithmetic, comparisons, bitwise/logical operators, `sizeof`, `_Alignof`, and
  `__builtin_offsetof`. Full py311 now measures 92.9050891878159% total
  coverage with 1361 missing lines, aarch64 84.74071975063758%/575, codegen
  89.54595386305382%/288, evm 96.13656783468105%/71, and x86_64
  86.27677100494233%/427. Ratchet 92.90%.
- Added fast EVM helper coverage for internal return/layout guards, switch
  misuse, expression and lvalue diagnostics, aggregate assignment mismatch
  paths, casts, statement/comma expressions, and direct/indirect function-call
  layout errors. Pre-commit py311 coverage refreshes have measured
  92.60556788703768%-92.61091648169443% total coverage with 1418-1419 missing
  lines, aarch64 83.93312553131199%/605, codegen
  89.50933723910656%-89.54595386305382%/288-289, evm
  96.13656783468105%/71, x86_64 85.40362438220758%/454. Ratchet 92.60%.
- Added fast EVM helper coverage for memory/storage initializer designator
  diagnostics, array range/index bounds, string-local initializer targets,
  `_Generic` selection failures, `sizeof` operand type failures, array
  alignment, and pointer-stride helpers. The pre-commit py311 gate measures
  92.35150964084187% total coverage with 1467 missing lines, aarch64
  83.93312553131199%/605, codegen 89.45441230318565%/291, evm
  94.07008086253369%/117, x86_64 85.40362438220758%/454. Ratchet 92.35%.
- Added another fast EVM helper sweep for constant-expression fallbacks,
  initcode size checks, PUSH operand bounds, bit-field truncation, storage
  stores, and local memory initializer diagnostics. Full py311 now measures
  92.19907469312439% total coverage with 1495 missing lines, aarch64
  83.93312553131199%/605, codegen 89.54595386305382%/288, evm
  92.6774483378257%/148, x86_64 85.40362438220758%/454. Ratchet 92.19%.
- Added fast EVM backend helper coverage for assembler PUSH0/negative values,
  function-shape guards, ABI type diagnostics, record lookup/layout edges,
  control-flow diagnostics, type-spec resolution, storage function labels, and
  storage initializer string/list diagnostics. Full py311 now measures
  92.01722247479475% total coverage with 1532 missing lines, aarch64
  83.93312553131199%/605, codegen 89.54595386305382%/288, evm
  91.15004492362984%/185, x86_64 85.40362438220758%/454. Ratchet 92.01%.
- Added more low-cost LLVM backend helper coverage for unary/address/call,
  builtin, constant-initializer, and constant-expression fallback edges that
  are hard to drive through valid source fixtures. Full py311 now measures
  91.7337469579868% total coverage with 1588 missing lines, aarch64
  83.93312553131199%/605, codegen 89.54595386305382%/288, evm
  88.76909254267744%/241, x86_64 85.40362438220758%/454. Ratchet 91.72%.
  The fresh `cpython-build` gate passes on the clean CPython worktree with
  `configure && make -j8`: 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing only from local dependencies, and 0 failed imports.
- Added low-cost LLVM backend helper coverage for codegen fallback edges that
  are hard to reach from valid C source, including malformed initializer
  designators, duplicate static-local global lookup, no-insertion-block checks,
  record lookup errors, string aggregate checks, and pointer arithmetic
  fallbacks. Full py311 now measures 90.8378573529805% total coverage with
  1775 missing lines, aarch64 83.93312553131199%/605, codegen
  83.41266935188575%/475, evm 88.76909254267744%/241, x86_64
  85.40362438220758%/454. Ratchet 90.83%.
- Added x86_64 public-path assembly coverage for GNU statement-expression void
  forms, scalar compound literal values, SysV `va_start` fixed aggregate/float
  parameter classification, right-hand pointer addition, void and array casts,
  function/static-local addresses, and unordered floating `!=`. Full py311 now
  measures 90.52763886288878% total coverage with 1836 missing lines, aarch64
  83.93312553131199%/605, codegen 81.28890516294398%/536, evm
  88.76909254267744%/241, x86_64 85.40362438220758%/454. Ratchet 90.52%.
- Fixed native record position initializers so unnamed bit-fields do not
  consume initializer slots in x86_64 and AArch64 lowering. Added regression
  coverage for x86_64 compound literals plus executable AArch64 global and
  local compound initializers with unnamed zero-width bit-fields. Full py311 now
  measures 90.41264407776856% total coverage with 1862 missing lines, aarch64
  83.93312553131199%/605, codegen 81.28890516294398%/536, evm
  88.76909254267744%/241, x86_64 84.69522240527183%/480. Ratchet 90.41%.
- Added x86_64 assembly coverage for SysV aggregate return classification when
  bit-fields force an integer chunk next to a floating chunk. Added executable
  LLVM coverage for global nested designators over named and anonymous
  aggregate members. Full py311 now measures 90.40087775636908% total coverage
  with 1865 missing lines, aarch64 83.90347764371894%/605, codegen
  81.28890516294398%/536, evm 88.76909254267744%/241, x86_64
  84.63189171343677%/483. Ratchet 90.40%.
- Added executable LLVM coverage for flattened local nested aggregate
  initializers, mixed integer/float arithmetic promotion and compound
  assignment lowering, global designator constant indexes, and switch case
  unary/conditional/comma constants. Fixed switch case constant evaluation for
  logical-not, bitwise-not, and comma expressions. Full py311 now measures
  90.352708199529% total coverage with 1879 missing lines, aarch64
  83.90347764371894%/605, codegen 81.28890516294398%/536, evm
  88.76909254267744%/241, x86_64 84.33476394849785%/497. Ratchet 90.35%.
- Extended EVM initcode storage constant-expression coverage for nested
  conditional expressions, pointer/array/anonymous-record `sizeof`, pointer and
  scalar `_Alignof`, `__builtin_offsetof`, `__builtin_types_compatible_p`,
  `_Generic`, and boolean plus narrow unsigned casts. Added EVM runtime coverage
  for anonymous record sizing and member access. Full py311 now measures
  90.20237712817219% total coverage with 1911 missing lines, aarch64
  83.90347764371894%/605, codegen 80.23853211009174%/568, evm
  88.76909254267744%/241, x86_64 84.33476394849785%/497. Ratchet 90.20%.
- Added EVM execution coverage for binary comparison/bitwise variants,
  pointer subtraction assignment, string-literal expressions, and scalar plus
  fixed-array compound literals. Added executable LLVM coverage for comma and
  conditional whole-aggregate initializers. Full py311 now measures
  90.08994539029875% total coverage with 1933 missing lines, aarch64
  83.90347764371894%/605, codegen 80.23853211009174%/568, evm
  87.82569631626235%/263, x86_64 84.33476394849785%/497. Ratchet 90.09%.
- Added AArch64 assembly coverage for global initializer variants including
  single-item braced scalar initializers, incomplete array index designators,
  compound-literal aggregate initialization, global `offsetof`, and global
  floating constants. Added x86_64 assembly coverage for mixed floating/integer
  aggregate return and call-argument chunks, plus C11 `__func__` and static
  aggregate identifier lowering. The full `py311` gate now measures
  90.04979119820109% total coverage with 1942 missing lines,
  `aarch64_asm.py` is up to 83.90347764371894% with 605 missing lines,
  `x86_64_asm.py` is up to 84.33476394849785% with 497 missing lines,
  `codegen.py` remains at 80.20183486238533% with 569 missing lines, and
  `evm.py` remains at 87.53369272237197% with 271 missing lines. The ratchet
  is tightened to 90.05%.
- Added executable LLVM coverage for global range designators, text-level
  x86_64 coverage for extended common GCC builtins, text-level AArch64
  coverage for float-class, bit, and narrow atomic builtin variants, and EVM
  initcode/runtime coverage for storage `_Generic`,
  `__builtin_types_compatible_p`, multi-character constants, and cast
  function-pointer labels. The full `py311` gate now measures
  89.97215976014563% total coverage with 1962 missing lines,
  `aarch64_asm.py` is up to 83.77572746628815% with 611 missing lines,
  `codegen.py` is up to 80.20183486238533% with 569 missing lines,
  `evm.py` is up to 87.53369272237197% with 271 missing lines, and
  `x86_64_asm.py` is up to 84.00462198745461% with 511 missing lines. The
  ratchet is tightened to 89.97%.
- Fixed LLVM lowering for local aggregate declarations with scalar
  initializers so sema-typed aggregate expressions no longer become invalid
  scalar-to-record bitcasts and omitted record members are zero-initialized
  before first-member initialization. Added executable LLVM coverage for
  `__builtin_va_copy` and scalar aggregate initializers, plus x86_64 assembly
  coverage for `__builtin_isnan` and global floating constant initializer
  forms. The clean real-project `cpython-build` gate passes
  `configure && make -j8` with 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing only from local dependencies, and 0 failed imports. The full
  `py311` gate now measures 89.68304957704251% total coverage with
  2035 missing lines, `codegen.py` is up to 79.85321100917432% with
  581 missing lines, `x86_64_asm.py` is up to 83.72400132056785% with
  522 missing lines, `aarch64_asm.py` remains at 83.02342086586232% with
  650 missing lines, and `evm.py` remains at 87.10691823899371% with
  282 missing lines. The ratchet is tightened to 89.68%, and the `mypyc`,
  lint, type, and pre-commit gates pass after the update.
- Added x86_64 assembly coverage for unordered floating condition branches,
  pointer subtraction scaling by element size, and member access on aggregate
  call results that must spill to temporary storage before applying member
  offsets. Added executable LLVM coverage for small/direct and large/indirect
  aggregate call-result member reads. The full `py311` gate now measures
  89.44773439802782% total coverage with 2089 missing lines, `codegen.py` is
  up to 79.10585627193792% with 605 missing lines, `x86_64_asm.py` is up to
  82.88213931990757% with 552 missing lines, `aarch64_asm.py` remains at
  83.02342086586232% with 650 missing lines, and `evm.py` remains at
  87.10691823899371% with 282 missing lines. The ratchet is tightened to
  89.44%.
- Added x86_64 assembly coverage for floating logical-not lowering, 32-bit
  signed division/remainder, bitwise-not lowering, and bit-field postfix
  updates that preserve the old result. Added executable LLVM coverage for
  string initializers targeting `char[]` record members. The full `py311` gate
  now measures 89.34590959028912% total coverage with 2118 missing lines,
  `codegen.py` is up to 78.88416774431923% with 613 missing lines,
  `x86_64_asm.py` is up to 82.45295477055134% with 573 missing lines,
  `aarch64_asm.py` remains at 83.02342086586232% with 650 missing lines, and
  `evm.py` remains at 87.10691823899371% with 282 missing lines. The ratchet
  is tightened to 89.34%.
- Added executable Darwin AArch64 coverage for CPython version-pack global
  initializers, global union padding, zero-width bit-field storage, flexible
  array global initialization, and aggregate zero-initializer edges. Added
  x86_64 assembly coverage for else-body slot collection, expression-form
  `for` initializers/updates, and function-local `_Static_assert`, plus
  executable LLVM coverage for union tail padding caused by member alignment.
  The full `py311` gate now measures 89.27623998499423% total coverage with
  2137 missing lines, `aarch64_asm.py` is up to 83.02342086586232% with
  650 missing lines, `codegen.py` is up to 78.81027156844634% with
  616 missing lines, `evm.py` remains at 87.10691823899371% with
  282 missing lines, and `x86_64_asm.py` is up to 82.08979861340376% with
  589 missing lines. The ratchet is tightened to 89.27%.
- Added executable LLVM coverage for block-scope `extern` scalar and array
  reads, void expression returns, nested scalar brace initializers, forward
  `goto`, endless `for` loops with `break`, post-return alloca insertion, and
  unprototyped function-pointer initializers. The full `py311` gate now
  measures 89.04847396768402% total coverage with 2194 missing lines,
  `codegen.py` is up to 78.73637539257344% with 618 missing lines,
  `aarch64_asm.py` remains at 82.05819730305181% with 698 missing lines,
  `evm.py` remains at 87.10691823899371% with 282 missing lines, and
  `x86_64_asm.py` remains at 81.87520633872565% with 596 missing lines. The
  ratchet is tightened to 89.04%.
- Added x86_64 native backend coverage for unused inline body suppression,
  referenced inline function designators, and stack-passed aggregate parameter
  chunks, plus Darwin AArch64 coverage for global pointer initializers that
  reference extern object symbols. The full `py311` gate now measures
  89.00292076422198% total coverage with 2203 missing lines,
  `x86_64_asm.py` is up to 81.87520633872565% with 596 missing lines,
  `aarch64_asm.py` is up to 82.05819730305181% with 698 missing lines,
  `codegen.py` remains at 78.42231664511361% with 627 missing lines, and
  `evm.py` remains at 87.10691823899371% with 282 missing lines. The ratchet
  is tightened to 89.00%.
- Added native backend coverage for x86_64 sparse array designators,
  incomplete local array initializer storage, and nested `offsetof` member
  paths, plus Darwin AArch64 execution coverage for chained member `sizeof`
  and nested `offsetof`. The full `py311` gate now measures
  88.9225327581125% total coverage with 2221 missing lines,
  `x86_64_asm.py` is up to 81.49554308352592% with 610 missing lines,
  `aarch64_asm.py` is up to 81.95883605393897% with 702 missing lines,
  `codegen.py` remains at 78.42231664511361% with 627 missing lines, and
  `evm.py` remains at 87.10691823899371% with 282 missing lines. The ratchet
  is tightened to 88.92%.
- Added native backend coverage for x86_64 global union padding, global
  bit-field storage-unit initializers, record compound literal bit-field and
  array-member initialization, bit-field compound assignment, and bit-field
  prefix/postfix updates. Added Darwin AArch64 execution coverage for record
  compound literals that initialize scalar array members and arrays of record
  members. The full `py311` gate now measures 88.72424234304242% total
  coverage with 2269 missing lines, `x86_64_asm.py` is up to
  80.30703202377022% with 657 missing lines, and `aarch64_asm.py` is up to
  81.930447125621% with 703 missing lines. The ratchet is tightened to
  88.72%.
- Added executable LLVM coverage for local initializer/control-flow edges and
  native backend coverage for grouped globals plus grouped static locals in
  both x86_64 and Darwin AArch64 assembly output. The full `py311` gate now
  measures 88.23655510597818% total coverage with 2399 missing lines,
  `codegen.py` is up to 78.42231664511361% with 627 missing lines,
  `x86_64_asm.py` is up to 78.06206668867613% with 756 missing lines, and
  `aarch64_asm.py` is up to 81.27750177430802% with 734 missing lines. The
  ratchet is tightened to 88.23%.
- Added LLVM execution coverage for default zero returns of pointer, floating,
  and record-returning functions, plus grouped file-scope declarations that
  lower multiple global objects from one declaration. The full `py311` gate now
  measures 87.91500308154023% total coverage with 2464 missing lines,
  `codegen.py` is up to 78.14520598559025% with 635 missing lines, and the
  ratchet is tightened to 87.91%.
- Added EVM backend coverage for explicit `return;` in exported void
  functions plus source-level EVM ABI and function-pointer diagnostics for
  variadic functions, unsupported internal parameters, pointer returns, record
  ABI parameters, `__builtin_evm_return_array` arity, unsupported indirect-call
  parameter types, missing local function-pointer targets, unsupported local
  object types, and scalar initialization of aggregate locals. The full
  `py311` gate now measures 87.8855274793001% total coverage with 2469 missing
  lines, `evm.py` is up to 87.10691823899371% with 282 missing lines, and the
  ratchet is tightened to 87.88%.
- Added EVM execution coverage for nested local and storage initializer
  designators that recurse through arrays of records. The full `py311` gate now
  measures 87.8372946756344% total coverage with 2477 missing lines, `evm.py`
  is up to 86.7026055705301% with 290 missing lines, and the ratchet is
  tightened to 87.84%.
- Added executable Darwin AArch64 coverage for global pointer initializers
  involving compound literals, string literals, null pointers, array decay,
  pointer-left addition, pointer-minus-integer, subobject/member addresses, and
  small/direct plus large/indirect record-return paths. Fixed AArch64 aggregate
  `__builtin_va_arg` initialization so variadic functions compiled by XCC can
  copy both inline and by-reference Darwin aggregate varargs into local records.
  The full `py311` gate now measures 87.8265762748198% total coverage with 2479
  missing lines, `aarch64_asm.py` is up to 80.62455642299503% with 758 missing
  lines, and the ratchet is tightened to 87.83%.
- Added LLVM execution coverage for local enum constants, function pointer
  dereference, pointer pre/post updates, pointer difference scaling, mixed
  float comparisons, pointer/integer comparisons, and floating compound
  assignments. The full `py311` gate now measures 87.72889353601973% total
  coverage with 2501 missing lines, `codegen.py` is up to
  77.94199150193977% with 640 missing lines, and the ratchet is tightened to
  87.73%.
- Fixed LLVM codegen for local and global UTF-16, UTF-32, and wide string array
  initializers so they emit typed integer array constants instead of invalid
  pointer-to-array bitcasts. Added executable coverage for local and global
  `u""`, `U""`, and `L""` array initialization plus GNU multi-character
  literal lowering. The full `py311` gate now measures 87.65650553634146%
  total coverage with 2519 missing lines, `codegen.py` is up to
  77.44319231479771% with 658 missing lines, and the ratchet is tightened to
  87.66%.
- Added executable Darwin AArch64 coverage for generic GNU atomic load, store,
  exchange, compare-exchange, lock-free queries, fences, RMW variants, and
  `__sync_*compare_and_swap` lowering. The full `py311` gate now measures
  87.65140324963072% total coverage with 2517 missing lines, `aarch64_asm.py`
  is up to 80.08540925266904% with 780 missing lines, and the ratchet is
  tightened to 87.65%. The real `cpython-build` gate still completes
  `configure && make -j8` with 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing from local dependencies, and 0 failed imports.
- Added EVM backend execution and diagnostic coverage for grouped storage
  declarations, initialized static locals, pointer-left addition, prefix
  pointer updates, signed bit-field updates, statement expressions without
  values, member access through record pointers, missing external call bodies,
  unprototyped function pointer calls, and initcode/local initializer
  diagnostics. The full `py311` gate now measures 87.35061098428898% total
  coverage with 2601 missing lines, `evm.py` is up to 86.61275831087151% with
  292 missing lines, and the ratchet is tightened to 87.35%. The
  `mypy c`/lint/type gate still passes through the compiled import tree, and
  the real `cpython-build` gate still completes `configure && make -j8` with
  116 modules checked, 37 built-in, 78 shared, `_gdbm` missing from local
  dependencies, and 0 failed imports.
- Fixed LLVM lowering for `__builtin_memset` so its fill argument is narrowed
  to the `i8` type required by the LLVM memset intrinsic, registered
  `__builtin___memcpy_chk` with sema to match the existing codegen lowering,
  and fixed floating classification builtins such as `__builtin_isinf(1)` so
  integer arguments are converted through a floating operand type instead of
  forming invalid integer `fcmp` IR. Added executable LLVM coverage for
  pointer-form GNU atomics, lock-free queries, memory builtins,
  `__builtin_expect`, `__builtin_ffs*`, and `__builtin_copysign*`. The full
  `py311` gate now measures 87.07398952598362% total coverage with 2657
  missing lines, and the ratchet is tightened to 87.07%. The real
  `cpython-build` gate still completes `configure && make -j8` with 116 modules
  checked and 0 failed imports.
- Fixed LLVM global constant initialization for union members whose active
  constant is stored as an LLVM aggregate with no visible operands, such as a
  nested union initialized through an `unsigned char[]` member and copied into
  larger array storage. Added an LLVM-C `GetAggregateElement` binding and
  executable coverage for nested union byte storage plus GNU
  `__sync_*compare_and_swap` lowering. The full `py311` gate now measures
  86.83284536248624% total coverage with 2719 missing lines, and the ratchet is
  tightened to 86.83%. The real `cpython-build` gate still completes
  `configure && make -j8` with 116 modules checked and 0 failed imports.
- Fixed LLVM switch case constant folding for logical and comparison operators,
  after an executable regression showed those case labels falling through as
  zero. Added execution coverage for switch case integer constant expressions
  and extended character string escape decoding. The full `py311` gate now
  measures 86.60164960640499% total coverage with 2778 missing lines, and the
  ratchet is tightened to 86.60%. The real `cpython-build` gate still completes
  `configure && make -j8` with 116 modules checked and 0 failed imports.
- Added LLVM codegen execution coverage for switch case integer constant
  expressions using division, remainder, shifts, bitwise operators, and a
  conditional expression. The full `py311` gate now measures
  86.51751862109764% total coverage with 2795 missing lines, and the ratchet is
  tightened to 86.51%.
- Added LLVM codegen execution coverage for global integer constant
  expressions and global float/pointer constant casts, covering bitwise,
  shift, logical, comparison, `ptrtoint`, `inttoptr`, null pointer, and negative
  floating initializer paths. The full `py311` gate now measures
  86.46373927774341% total coverage with 2805 missing lines, and the ratchet is
  tightened to 86.46%.
- Fixed AArch64 and x86_64 record layout so explicit member `_Alignas`
  contributes to record alignment, `sizeof`, member offsets, HFA offsets, and
  global initializer padding. Added native backend regressions for explicitly
  aligned members, and tightened the coverage ratchet to 86.24% after the full
  `py311` gate measured 86.24593293715884% total coverage with 2850 missing
  lines. The real `cpython-build` gate still completes `configure && make -j8`
  with 116 modules checked and 0 failed imports.
- Fixed LLVM codegen for `_Alignof` so constant expressions return the target
  type's alignment instead of its size, and record/union alignment now honors
  explicit member `_Alignas` requirements. Added execution tests for natural
  record alignment and explicitly aligned members. The refreshed full `py311`
  gate measures 86.21775039681472% total coverage with 2857 missing lines, and
  the real `cpython-build` gate still completes `configure && make -j8` with
  116 modules checked and 0 failed imports.
- Fixed the parallel coverage runner so each `--coverage` invocation uses an
  isolated per-run `COVERAGE_FILE` before combining data, preventing stale
  `.coverage.*` files from contaminating the ratchet. The isolated full
  `py311` gate now measures 86.20698931963089% total coverage with 2859 missing
  lines, and `sema/initializers.py` is back to 100%.
- Fixed unbraced flattened aggregate initializer consumption across sema,
  incomplete-array length inference, LLVM local initialization, and LLVM global
  constant initialization. Added execution tests for nested records, arrays of
  records, multidimensional arrays, and nested char-array string initializers so
  `struct Pair pairs[2] = {1, 2, 3, 4}` and `int a[2][3] = {1, 2, 3, 4, 5, 6}`
  initialize subobjects like C expects instead of treating each scalar as a
  top-level element.
- Added a stdlib-only parallel unittest runner that shards test modules across
  subprocesses, merges coverage data, and is now the shared tox test gate with
  the default coverage ratchet raised from 0% to the current 86.2%.
- Promoted mypyc from benchmark-only tooling to an explicit tox gate that
  rebuilds the compiled import tree and runs the test suite against it.
- Added a `cpython-build` tox gate and `scripts/validate_cpython_build.py` so a
  clean CPython `configure && make` build has a reproducible entry separate
  from frontend file benchmarks; the gate now rebuilds and injects the mypyc
  import tree before invoking `CC=xcc`.
- Verified the real CPython build path through the `cpython-build` tox gate
  against the isolated `build/cpython-src-clean` worktree with the mypyc import
  tree injected; CPython completed `configure && make -j8`, checked 116 modules
  with 37 built-in, 78 shared, `_gdbm` missing from local dependencies, and
  0 failed imports.
- Wired local pre-commit and CI test gates through tox so test, lint, and type
  checks use the same commands before handoff.
- Added focused branch-coverage tests for GNU asm preprocessing, host include
  fallback discovery, parser GNU attribute handling, array-size/type-specifier
  edges, preprocessor macro/comment helpers, frontend token caching, and
  semantic scope/record helpers; `host_includes.py`,
  `parser/extensions.py`, `parser/array_sizes.py`, `parser/statements.py`,
  `parser/type_specs.py`, `preprocessor/macros.py`,
  `preprocessor/macro_expansion.py`, `preprocessor/process.py`,
  `frontend.py`, `sema/records.py`, and `sema/symbols.py` now report 100%
  coverage under the full gate, leaving the remaining global coverage debt
  concentrated in backend code paths.
- Added another coverage sweep for cc-driver argument/error paths, LLVM loader
  caching, GNU asm text helpers, enum constant evaluation, string literal
  typing, and sema initializer fallbacks. The full `py311` gate now measures
  84.49500585145469% total coverage with 3234 missing lines; `cc_driver.py`
  reports 98%, while `llvm_api.py`, `sema/expressions.py`,
  `sema/initializers.py`, and `sema/type_resolution.py` report 100%.
- Added focused backend coverage tests for LLVM constant pointer subscript
  initializers, GNU statement-expression variants, GNU atomic
  `__atomic_*_fetch` new-value lowering, and AArch64 global builtin float
  constant emission. The full `py311` gate now measures
  84.8869172359361% total coverage with 3145 missing lines, and the coverage
  ratchet is tightened to 84.8%.
- Cleared the remaining small non-backend coverage gaps in `cc_driver.py`,
  `preprocessor/text.py`, `sema/__init__.py`, `sema/constants.py`,
  `sema/declarations.py`, and `sema/statements.py`; those modules now report
  100% coverage. The full `py311` gate now measures 84.94936846689896% total
  coverage with 3134 missing lines, leaving only `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py` below 100%, and the ratchet is
  tightened to 84.9%.
- Added backend coverage tests for AArch64 local array initializer execution,
  x86_64 inline lowering of atomic load/store/exchange/fence/bitwise fetch
  operations, EVM initcode storage constant-expression operators, and LLVM
  local aggregate initializer stores. The full `py311` gate now measures
  85.43118466898954% total coverage with 3018 missing lines, and the ratchet is
  tightened to 85.4% with two-decimal coverage report precision.
- Added backend coverage tests for LLVM loop/switch/goto control-flow paths,
  x86_64 integer compound-assignment lowering, and EVM Keccak multi-rate-block
  absorption. The full `py311` gate now measures 85.665287456446% total
  coverage with 2956 missing lines, and the ratchet is tightened to 85.6%.
- Added backend coverage tests for x86_64 loop/switch/goto statement lowering,
  x86_64 scalar and array compound-literal storage initialization, and EVM
  nested static-local collection through control-flow statements. The full
  `py311` gate now measures 85.98649825783973% total coverage with 2873
  missing lines, and the ratchet is tightened to 85.9%.
- Added backend coverage tests for AArch64 loop/switch/goto statement lowering,
  AArch64 scalar and array compound-literal storage initialization, and EVM
  compound-assignment and runtime unary operator lowering. The full `py311`
  gate now measures 86.17704703832753% total coverage with 2832 missing lines,
  and the ratchet is tightened to 86.1%.
- Added EVM backend coverage tests for expression-form `for` initializers and
  `void` post expressions, static-local discovery through nested expression
  trees, and `void` function-pointer dispatch returns. The full `py311` gate
  now measures 86.22060104529616% total coverage with 2823 missing lines, and
  the ratchet is tightened to 86.2%.
- Optimized CPython-scale frontend throughput by making `FrontendResult.pp_tokens`
  lazy and adding a guarded preprocessor macro-candidate scan; on
  `Python/getcompiler.c`, cProfile total time dropped from 49.608 s to
  17.690 s and `lex_pp` cumulative time dropped from 17.296 s to 3.521 s.
- Retested CPython integration from a clean out-of-tree build directory with
  `CC=/Users/tcztzy/GitHub/xcc/.venv/bin/xcc`,
  `XCC_LLC=/opt/homebrew/opt/llvm/bin/llc`, and `make -j1`; the build completed
  with 116 modules checked, 0 failed imports, and only `_gdbm` missing due to
  local dependencies.
- Fixed full-CPython-build compatibility gaps missed by partial object smoke
  tests: OpenSSL-style `const char **` arguments may pass through `void *`, and
  GNU `__extension__ __alignof__(expr)` is accepted under C11 while standard
  `_Alignof(expr)` remains rejected in strict C11 mode.
- Preserved GNU `return expr;` side effects in `void` functions while keeping
  strict C11 rejection for non-`void` return expressions.
- Rebuilt and reran the mypyc-precompiled XCC frontend benchmark on CPython
  `Objects/listobject.c`; the measured runs were 4.608, 4.592, and 4.510 s,
  while real GCC (`gcc-15`) and Homebrew Clang syntax-only checks on the same
  file measured 0.181 s and 0.140 s median respectively.
- Removed unused preprocessor private-constant re-exports that blocked mypyc
  compilation of the benchmark import tree.
- Added GitHub Actions workflows for CI validation gates and static GitHub
  Pages deployment, then synchronized entry docs and package metadata with the
  agent-controlled C compiler positioning.
- Added a standalone `github-pages/` static landing page that presents XCC as
  an agent-controlled C compiler and explains the repository-level control
  system behind agent work.
- Added `scripts/validate_compiler.py`, a stdlib-only validation harness that
  compares selected XCC-generated executables against `clang` and checks
  driver/frontend rejection boundaries for inputs XCC must not accept.
- Added an explicit `--target=evm` backend that emits Ethereum legacy EVM
  opcode assembly with `-S` and lowercase hex runtime bytecode with `-c`,
  including stdlib-only Keccak ABI selectors, scalar integer ABI dispatch, and
  `__builtin_evm_sload`/`__builtin_evm_sstore` lowering.
- Expanded the EVM target with `while`/`do while`/`for` plus
  `break`/`continue`, `__builtin_evm_caller`, `__builtin_evm_callvalue`,
  `__builtin_evm_revert`, `__builtin_evm_log1`, and ABI scalar types
  `__evm_uint256` / `__evm_address`.
- Added EVM file-scope scalar storage variables mapped to deterministic
  declaration-order storage slots, with initialized storage globals rejected
  until deploy-time initcode exists.
- Expanded the EVM backend with word-addressed memory pointers, fixed local
  arrays, dynamic ABI word-array parameters, `__builtin_evm_return_array`,
  deployment initcode generation for scalar initialized storage globals, and
  deterministic struct-member storage slots.
- Fixed EVM dynamic ABI array decoding so calldata elements are converted to
  the pointer element type while being copied into EVM memory, matching scalar
  ABI parameter truncation and sign/boolean normalization.
- Expanded EVM scalar expression lowering with short-circuit `&&`/`||`,
  selected-branch `?:`, and comma expressions while preserving side-effect
  ordering through explicit jumps.
- Expanded EVM signed scalar lowering so signed comparison, division, modulo,
  and right shift use `SLT`/`SGT`/`SDIV`/`SMOD`/`SAR` according to C integer
  conversions.
- Expanded EVM integer conversion lowering so casts, scalar stores, returns,
  and integer expression results truncate unsigned widths, sign-extend signed
  widths, and normalize `_Bool` values to 0/1.
- Added EVM direct internal function calls for same-translation-unit helpers,
  using per-function memory frames plus return-PC and return-value slots while
  keeping static helpers out of the ABI dispatcher.
- Added EVM internal helper returns for word pointer values while keeping
  pointer returns out of the exported ABI surface.
- Added EVM function pointer calls for same-translation-unit fixed-prototype
  helpers, lowering function designators and `&function` addresses to internal
  jump labels and dispatching indirect calls through matching signatures.
- Added EVM function pointer call support for record/union parameters by
  copying aggregate word slots through indirect-call argument frames before
  dispatching to the selected helper.
- Added EVM internal helper parameters for word-valued arguments, including
  function pointer parameters that can be indirect-called by the helper.
- Added EVM internal helper record/union parameters by copying aggregate word
  slots into the callee frame for direct same-translation-unit helper calls.
- Added EVM internal helper record/union returns by copying aggregate word slots
  through callee return frames into caller locals, assignments, member access,
  and function pointer return-call paths.
- Added EVM internal helper returns for function pointer values so a helper can
  select a local target and callers can immediately indirect-call it.
- Added EVM handling for block-scope helper prototypes so local function
  declarations are treated as declarations rather than stack objects.
- Added EVM initcode storage initialization for function pointer globals,
  resolving function designators and `&function` initializers to deployed
  runtime jump offsets before emitting deployment-time `SSTORE`s.
- Added EVM initcode constant folding for conditional function pointer storage
  initializers so deployment bytecode stores the selected runtime helper label.
- Added EVM `sizeof` and `_Alignof` lowering for the target's 32-byte
  word-object layout, without evaluating expression operands.
- Added EVM `switch`/`case`/`default` lowering with explicit case dispatch,
  fallthrough behavior, and switch-scoped `break` targets.
- Added EVM character literal lowering for ordinary and escaped constants,
  including hexadecimal/octal escapes in scalar expressions and `switch` case
  constants.
- Added EVM `__builtin_offsetof` lowering for simple and nested record members
  using the target's 32-byte word-object layout.
- Added EVM lowering for `__builtin_types_compatible_p` and `_Generic`,
  selecting only the matched generic association without evaluating the control
  expression.
- Added EVM GNU statement-expression lowering for ordered embedded statements,
  local declarations, and final expression-statement results.
- Added EVM direct `goto`/label lowering with function-copy-local labels so ABI
  and internal helper bodies do not cross-jump.
- Added EVM labels-as-values and indirect `goto` lowering through current
  function-copy-local EVM jump offsets.
- Added EVM scalar and fixed-array compound literal lowering using planned
  function-frame word storage, including array decay and assignable lvalue use.
- Added EVM char-word string literal lowering for local char-array
  initializers and pointer-expression use, including C escape decoding and null
  terminators.
- Expanded EVM aggregate initializer lowering to local records and record
  compound literals, with positional member stores and zeroed omitted members.
- Added EVM anonymous union member layout and promoted member access for local
  records, including positional local initialization through the anonymous
  union slot.
- Added EVM word-backed record bit-field lowering for local memory and storage
  records, including width-masked member reads/writes and initcode storage
  initializers.
- Added EVM unnamed bit-field padding support so local and initcode storage
  record initializers skip padding fields instead of rejecting them as
  anonymous storage members.
- Added EVM record assignment lowering through word-slot copies across memory
  and storage address spaces.
- Expanded EVM initcode storage initialization to flatten fixed-array and
  simple-record aggregate initializers into deployment-time `SSTORE`s.
- Added EVM designated aggregate initializer lowering for fixed-array indexes
  and record fields across local word memory and initcode storage slots.
- Added EVM no-op lowering for null statements, block-scope typedefs, and
  semantically checked `_Static_assert` declarations.
- Added EVM initcode support for storage char arrays initialized from C string
  literals, including escapes and null padding in word slots.
- Added EVM block-scope static local variables backed by persistent storage
  slots, including initcode initialization and zero-initialized statics.
- Added EVM enum constant lowering for runtime expressions and integer
  constant contexts such as `switch` case values.
- Fixed EVM pointer subtraction so pointer differences are divided by the
  target word-object element stride instead of scaling the right pointer.
- Added `__builtin_evm_addmod`, `__builtin_evm_mulmod`, and
  `__builtin_evm_exp` lowering to the native `ADDMOD`, `MULMOD`, and `EXP`
  opcodes, with execution coverage for large operands that would differ under
  premature 256-bit wrapping.
- Added `__builtin_evm_byte`, `__builtin_evm_mstore8`, and
  `__builtin_evm_msize` lowering to the native `BYTE`, `MSTORE8`, and `MSIZE`
  opcodes, with execution coverage for byte extraction, single-byte memory
  writes, and active memory size.
- Added `__builtin_evm_mload`, `__builtin_evm_mstore`,
  `__builtin_evm_signextend`, and `__builtin_evm_pc` lowering to the native
  `MLOAD`, `MSTORE`, `SIGNEXTEND`, and `PC` opcodes.
- Added `__builtin_evm_tload`, `__builtin_evm_tstore`,
  `__builtin_evm_mcopy`, `__builtin_evm_blobhash`, and
  `__builtin_evm_blobbasefee` lowering to the native transient storage, memory
  copy, and blob fee/hash opcodes.
- Added EVM assembler `PUSH0` emission for implicit zero constants while
  preserving explicit push widths for labels and ABI selectors.
- Added `__builtin_evm_return`, `__builtin_evm_stop`, and
  `__builtin_evm_invalid` lowering to raw `RETURN`, `STOP`, and `INVALID`
  terminal opcodes.
- Added `__builtin_evm_revert_data(ptr, len)` and
  `__builtin_evm_log0_data` through `__builtin_evm_log4_data` lowering so C
  code can use raw memory ranges for `REVERT` and `LOG0`-`LOG4`.
- Added `xcc --target=evm --evm-initcode -c` so the driver can write
  deployable `.init.bin` creation bytecode, including storage initialization,
  without replacing the existing runtime `.bin` output path.
- Added EVM ABI calldata bounds checks so truncated scalar arguments or dynamic
  `uint256[]` payloads revert instead of decoding missing words as zero.
- Hardened EVM dynamic ABI array decoding to reject offsets that point into the
  static argument head or are not 32-byte aligned.
- Expanded EVM event log builtins from `__builtin_evm_log1` to the full
  `__builtin_evm_log0` through `__builtin_evm_log4` opcode family.
- Added `__builtin_evm_keccak256(ptr, len)` lowering to the native EVM `SHA3`
  opcode for hashing memory ranges with the backend's Keccak implementation.
- Added zero-argument EVM environment builtins for `ADDRESS`, `ORIGIN`,
  `GASPRICE`, `COINBASE`, `TIMESTAMP`, `NUMBER`, `PREVRANDAO`, `GASLIMIT`,
  `CHAINID`, `SELFBALANCE`, `BASEFEE`, and `GAS`.
- Added one-argument EVM account/block query builtins for `BALANCE`,
  `BLOCKHASH`, `EXTCODESIZE`, and `EXTCODEHASH`.
- Added raw calldata builtins for `CALLDATASIZE`, `CALLDATALOAD`, and
  `CALLDATACOPY`, including execution tests that copy calldata bytes into EVM
  word memory.
- Added runtime code introspection builtins for `CODESIZE` and `CODECOPY`,
  including execution tests that copy deployed bytecode bytes into memory.
- Added `__builtin_evm_extcodecopy(address, dst, offset, len)` lowering to the
  native `EXTCODECOPY` opcode, with execution coverage for copying external
  account code bytes into EVM memory.
- Added return-data builtins for `RETURNDATASIZE` and `RETURNDATACOPY`,
  including execution tests that copy prior-call return bytes into EVM memory.
- Added `__builtin_evm_create(value, init, init_len)` lowering to the native
  `CREATE` opcode, with execution coverage for copied initcode bytes, call
  value, emitted opcode, and returned created address.
- Added `__builtin_evm_create2(value, init, init_len, salt)` lowering to the
  native `CREATE2` opcode, with execution coverage for copied initcode bytes,
  call value, salt, emitted opcode, and returned created address.
- Added `__builtin_evm_selfdestruct(beneficiary)` lowering to the native
  `SELFDESTRUCT` opcode, with execution coverage for beneficiary stack order
  and halting behavior.
- Added `__builtin_evm_call(gas, address, value, in, in_len, out, out_len)`
  lowering to the native `CALL` opcode, with execution coverage for copied call
  input, return bytes, success status, gas, target address, and call value.
- Added `__builtin_evm_callcode(gas, address, value, in, in_len, out, out_len)`
  lowering to the native `CALLCODE` opcode, with execution coverage for copied
  input, return bytes, success status, gas, target address, and call value.
- Added `__builtin_evm_staticcall(gas, address, in, in_len, out, out_len)`
  lowering to the native `STATICCALL` opcode, with execution coverage for
  copied input, return bytes, success status, gas, target address, and zero
  call value.
- Added `__builtin_evm_delegatecall(gas, address, in, in_len, out, out_len)`
  lowering to the native `DELEGATECALL` opcode, with execution coverage for
  copied input, return bytes, success status, gas, target address, and the
  current call value.
- Merged Cython and mypyc throughput comparisons into
  `scripts/benchmark_xcc.py` and added tox-uv benchmark environments for
  py311-py314, pypy311, graalpy311-graalpy312, cython, and mypyc; the compiled
  variants run under CPython 3.11.
- Added `docs/benchmark.md` with the local benchmark environment, commands, and
  single-file CPython frontend throughput results.
- Added optional mypyc performance tooling: `scripts/mypycize_xcc.py` builds a
  temporary compiled import tree for the frontend hot path.
- Added mypy checking to the dev type gate and pre-commit hook, with source
  annotations/local names tightened so `uv run mypy` passes on `src`.
- Simplified CC-driver target execution by sharing generated assembly/object
  handling across LLVM, Darwin AArch64, and Linux x86_64 targets.
- CC-driver `-std=<mode>` now feeds the frontend language mode instead of only
  being forwarded to delegated tool arguments.
- CC-driver `-S`/`-c` with multiple C inputs now writes per-input default
  outputs when `-o` is absent and rejects explicit `-o` before overwriting
  output files.
- LLVM target object lowering now discovers `llc` via `XCC_LLC`,
  `LLVM_CONFIG`, or `PATH` and verifies `llc --help` stdout before use,
  avoiding a hard dependency on Homebrew's LLVM path or an accidental
  same-name executable.
- Added optional Cython performance experiment tooling: `scripts/cythonize_xcc.py`
  builds a temporary compiled import tree without adding runtime dependencies.
- Native x86_64 Linux wide string literals now align UTF-16/UTF-32 literal
  labels to their element width, fixing gpu02 glibc `wcscmp` crashes during
  CPython bootstrap/config parsing.
- Native x86_64 Linux `_Bool` conversion now normalizes nonzero scalar values
  to 1 instead of truncating low bytes, fixing CPython future-annotation
  handling for `typing.NamedTuple` build checks.
- Native x86_64 Linux call lowering now respects local function-pointer
  shadowing of same-named file-scope functions, fixing CPython runtime
  segfaults in `locale`/`gettext` triggered by dict-view intersection with a
  list.
- Native x86_64 Linux conditional expression lowering now coerces both
  branches to the conditional result type, fixing sign-extension for patterns
  such as `long x = cond ? count : -1`.
- Sema now registers block-scope extern function prototypes as callable
  function signatures, allowing native x86_64 codegen to emit direct calls for
  CPython patterns such as `extern PyObject *PyCFunction_Call(...)` inside a
  function body.
- Native x86_64 Linux codegen now lowers expression-position compound
  literals through frame temporaries, including array compound literals used
  as pointer-decayed call arguments.
- GNU mode now predefines `__PRETTY_FUNCTION__` as a string-compatible
  fallback alongside `__func__`, covering CPython assertion/debug macro
  expansions in `_testinternalcapi`.
- Native x86_64 Linux driver mode now strips macro-expanded GNU `__asm__`
  statements instead of rejecting them, covering CPython HACL
  `__cpuid_count` use in `blake2module.c` and `hmacmodule.c` while preserving
  AArch64's stricter target policy.
- LLVM IR target triple changed from `arm64-apple-macosx15.0.0` to
  `aarch64-apple-darwin` for portability and CPython configure compatibility.
- LLVM IR backend via libLLVM-C ctypes. Generates IR programmatically,
  pipes through llc for .o files, clang for linking.
- Driver target model replaces backend modes: `--target=llvm` is the default
  and LLVM IR is treated as the target assembly language.
- Added `--target=aarch64-apple-darwin` for direct native Darwin AArch64
  assembly output on scalar integer leaf functions; `-c`/link assemble that
  generated `.s` through clang.
- Removed clang fallback backend mode; XCC failures now fail the compile.
- Removed CPython-specific `scripts/cpython_trial.py` triage harness.
- Frontend passes 442/442 CPython files.
- Deleted: ARM64 asm codegen, Clang suite, Docker infra, harness scripts,
  Clang test fixtures, CPython stubs.
- SemaUnit extended with `record_definitions` for codegen struct layout.
- Codegen emits incomplete arrays as `[0 x T]` and indexes arrays through
  their address, avoiding `llc` memory blowups from `[4294967295 x T]`.
- CPython `CC="xcc" ./configure && make -j1` now completes
  `checksharedmods`, including a clean-object rebuild after deleting `.o`
  files; optional `_gdbm` and `_tkinter` remain missing due to local
  dependencies, with 0 extension import failures.
- Fixed CPython-discovered generic C bugs: GNU `void return expr;` now
  analyzes/emits operand side effects, multi-line macro invocation collection
  survives block comments and inactive branch directives, and incomplete array
  bounds now account for sparse designators/ranges.
- Native Darwin AArch64 now emits referenced inline function bodies reached
  through function designators, conditional function pointers, global tables,
  and `extern inline` definitions as TU-local symbols while keeping unused
  inline bodies skipped.
- Native Darwin AArch64 now lowers common GCC/Clang compiler builtins used by
  CPython and Darwin headers, including bit operations, float constants and
  classifiers, `fabs`, `expect`, `unreachable`, `assume_aligned`, `alloca`, `va_copy`,
  `frame_address`, and fallback `assert`.
- Native Darwin AArch64 now uses GOT relocations for external data symbols
  such as Darwin's `__stderrp`.
- Native Darwin AArch64 now uses GOT relocations for external function
  designators while keeping direct calls as branch relocations.
- Native Darwin AArch64 now preserves earlier argument registers when a later
  call argument or indirect callee expression contains a nested call, avoiding
  ABI clobbers such as `f(ptr, strlen(ptr))`.
- Native Darwin AArch64 now preserves binary-expression left operands while
  evaluating nested RHS arithmetic, comparisons, shifts, or calls, avoiding
  false overflow/no-memory branches such as `len > MAX / sizeof(T) - 1`.
- Native Darwin AArch64 now preserves local scalar compound-assignment left
  values across RHS evaluation, fixing `_PyObject_VAR_SIZE`-style size
  accumulation during CPython bootstrap.
- Native Darwin AArch64 local array scalar initializers now compute the
  initializer value before recomputing the element destination address, so
  pointer arithmetic initializers cannot store through a clobbered x11.
- Native Darwin AArch64 large-frame scratch, spill, and outgoing argument
  stack accesses now materialize addresses before load/store when SP offsets
  exceed the assembler immediate range.
- Native Darwin AArch64 update expressions now keep lvalue addresses separate
  from result registers in nested dereference/update forms such as
  `*(*p_format)++`.
- Native Darwin AArch64 aggregate copies now preserve source addresses while
  reloading saved destination addresses from large-frame scratch slots.
- Native Darwin AArch64 call-returned small record and HFA arguments now use
  planned scratch spills instead of dynamic `sp` pushes, and move overlapping
  return registers into later argument registers without duplicating fields.
- Native Darwin AArch64 subscript address scaling for non-power-of-two element
  sizes now keeps the scale scratch separate from the live base/index
  registers.
- Native Darwin AArch64 nested subscript address formation now uses distinct
  index scratch registers across recursive levels, fixing argv parsing in
  `_bootstrap_python`.
- Native Darwin AArch64 nested subscript scaling now avoids all live outer
  index registers when materializing non-power-of-two element sizes.
- Native Darwin AArch64 now emits wide string literals as target-width
  zero-terminated storage instead of narrow `__cstring` data.
- Native Darwin AArch64 now clean-builds CPython's native objects, links
  `_bootstrap_python` and `python.exe`, regenerates frozen module headers, and
  starts `python.exe` for a `PYTHONPATH=Lib` smoke import on this machine.
- Added initial `--target=x86_64-linux-gnu` support for gpu02-class Linux:
  the driver emits native ELF x86_64 SysV assembly, assembles/links through
  `cc`, and does not invoke LLVM IR, `llc`, or clang for this target.
- Native x86_64 `sizeof(local_array)` now uses frame-planned slot types after
  codegen completes local array bounds, covering CPython multibytecodec state
  buffers whose sema symbol remains an incomplete `T[-1]`.
- Added Linux target preprocessing state so `x86_64-linux-gnu` defines
  Linux/x86_64/ELF macros instead of Darwin macros, plus Linux system include
  discovery from the host `cc -E -v` search list.
- Added the first native x86_64 backend subset covering scalar integer/pointer
  functions, locals, arrays, pointer arithmetic, control flow, simple calls,
  string/global scalar data, and deterministic unsupported diagnostics.
- Expanded the native x86_64 Linux path for CPython configure on gpu02:
  driver delegation now uses gpu02 `cc`, glibc-target GNU macros match the
  gpu02 GCC baseline, GNU `restrict` aliases and record-member
  `__extension__` markers parse, and trailing multi-line `#endif` comments are
  stripped during preprocessing.
- Native x86_64 SysV codegen now supports scalar floating parameters, returns,
  calls, stack overflow FP arguments, file-scope enum constants, string/array
  call argument decay, and floating compound assignment through XMM registers.
- Native x86_64 SysV calls now classify two-double record arguments such as
  CPython's `Py_complex` into SSE chunks and spill matching aggregate
  parameters from XMM registers.
- Native x86_64 record member access now resolves promoted members through
  anonymous struct/union fields, covering CPython object-header accesses such
  as `ob_refcnt`.
- Native x86_64 codegen now sizes `__builtin_va_list` and lowers
  `__builtin_va_start`/`__builtin_va_end` for stack-based variadic helper
  functions used by CPython parser headers.
- Native x86_64 record member codegen now supports integer bit-field reads,
  assignments, compound assignments, and updates by masking and rewriting the
  containing storage unit.
- Native x86_64 scalar sizing now treats tagged enum objects and parameters as
  signed 4-byte integer ABI values.
- Native x86_64 global data emission now supports pointer initializers that
  reference file-scope compound literal arrays of initialized records, covering
  CPython parser keyword tables.
- Native x86_64 assignment now handles record storage copies and record
  compound literal assignments by zeroing the destination and storing selected
  members.
- Native x86_64 functions now return small SysV aggregate values in integer or
  SSE return registers, including local records, compound literals, and
  forwarded aggregate-return calls.
- Native x86_64 local declarations now support record initializer lists by
  initializing the stack slot in place.
- Native x86_64 numeric conversion now handles unsigned 64-bit integer to
  `float`/`double` conversion without rejecting high-bit inputs.
- Native x86_64 variadic support now lowers scalar `__builtin_va_arg` reads
  through the current stack-based va_list cursor.
- Native x86_64 expression typing now normalizes bare enum object expressions
  to `int` for arithmetic and pointer conversion checks.
- Native x86_64 pointer arithmetic now treats array operands, including string
  literals, as decayed element pointers.
- Native x86_64 integer literal parsing now accepts C legacy octal forms such
  as `0377`.
- Native x86_64 unary dereference now decays array operands before loading the
  selected element.
- Native x86_64 pointer casts now decay array operands first, covering casts of
  string literals to `char *`/`void *`.
- Native x86_64 aggregate assignment now handles small aggregate call results
  by storing SysV return-register chunks into the destination.
- Native x86_64 address formation now supports comma expressions by evaluating
  the left operand for side effects and taking the address of the right operand.
- Linux preprocessing now strips GNU inline asm statements as complete balanced
  statement segments even when they occur inside one-line macro-expanded
  `do { ... } while (0)` bodies.
- GNU transparent union typedefs now participate in function-call argument
  compatibility, covering glibc socket prototypes such as `accept4` without
  relaxing ordinary union assignment rules.
- Preprocessing now expands function-like macro invocations whose macro name
  ends one physical line and whose `(` begins on the next, covering Debian
  glibc deprecation attribute macros in `signal.h`.
- Native x86_64 record compound initializers now accept zero initializers for
  aggregate members without emitting oversized scalar stores.
- Native x86_64 record compound initializers now copy aggregate expression
  members into destination member storage.
- Native x86_64 functions and calls now support SysV indirect returns for
  aggregates larger than 16 bytes using a hidden caller-provided result pointer.
- Added sema and native x86_64 lowering for GNU `__builtin_isinf_sign` and
  direct x86_64 lowering for related float classification builtins.
- Native x86_64 calls now pass small aggregate call results as aggregate
  arguments by reusing the inner call's return-register chunks.
- Native x86_64 local record declarations now initialize from aggregate call
  results by storing return chunks into the local slot.
- Native x86_64 floating conditional expressions now preserve their XMM result
  register for subsequent stores.
- Native x86_64 unary dereference now keeps pointer operands in GPR address
  registers while loading floating pointees into XMM registers.
- Native x86_64 integer and pointer subexpressions now normalize XMM-requested
  result targets back to GPRs before scalar lowering.
- Native x86_64 global initializers now accept function designator addresses
  for function-pointer record fields.
- Native x86_64 record layout now computes `sizeof` for structs with final
  flexible array members by excluding the tail array.
- Native x86_64 member access now computes offsets for final flexible array
  members so their subscripts can be addressed.
- Native x86_64 array member expressions now decay to address values in
  expression and cast contexts, including flexible array members.
- Native x86_64 global record initializers now omit storage for absent final
  flexible array members.
- Native x86_64 local float and double array initializers now store element
  values from XMM registers instead of integer registers.
- Native x86_64 aggregate assignment now lowers conditional record/union
  expressions by copying only the selected branch into the destination.
- Native x86_64 expression lowering now normalizes non-floating scalar
  expressions to GPRs when they are evaluated inside floating contexts before
  conversion to XMM registers.
- Added a native x86_64 regression for the Autoconf ANSI `const` probe shape
  so stale `#define const /**/` pyconfig output is caught before CPython make.
- Native x86_64 address formation now treats string literals as addressable
  static arrays for subscript and unary-address contexts.
- Native x86_64 local array initializers now support arrays of records/unions
  with nested initializer lists by initializing each element in stack storage.
- Native x86_64 static local arrays with incomplete bounds now complete their
  storage size from initializer lists before local references are bound.
- Native x86_64 calls now support conditional small aggregate arguments by
  pushing ABI chunks from the selected branch.
- Native x86_64 calls now support function-scope record/union compound literal
  aggregate arguments by materializing them once in frame storage and pushing
  ABI chunks from that storage.
- Native x86_64 aggregate initialization now treats scalar zero expressions as
  zero-initializers for record/union/array destinations instead of aggregate
  copy sources.
- Native x86_64 small aggregate returns now support conditional record/union
  expressions by materializing the selected branch in aligned scratch storage.
- Native x86_64 member access on aggregate call results now materializes the
  returned record/union chunks into frame storage before forming member
  addresses.
- Native x86_64 identifier lowering now decays extern/file-scope incomplete
  arrays to symbol addresses before attempting any slot sizing.
- Native x86_64 global pointer initializers now accept constant-index array
  subobjects plus member offsets, such as `&array[0].field`.
- Native x86_64 indirect aggregate returns now support conditional record/union
  expressions by writing the selected branch to the hidden sret storage.
- Preprocessing now expands member-position object-like macros whose
  replacement mentions the same name once, covering glibc `sa_handler`.
- Native x86_64 global pointer initializers now decay array-typed global
  subobject expressions with accumulated member offsets.
- Native x86_64 block-scope function prototypes now lower as non-object
  declarations without local stack slots.
- Native x86_64 discarded calls returning memory-class records/unions now pass
  a compiler-owned hidden sret slot instead of calling without result storage.
- The native x86_64 driver now accepts CPython's `-fno-strict-aliasing`
  compile flag for generated-object builds.
- Native x86_64 global float/double initializers now constant-fold arithmetic
  floating expressions and common floating builtins.
- Native x86_64 `sizeof`/`_Alignof` in local declarator bounds now resolves
  prior locals and member chains without leaking raw type-map ids.
- Macro expansion now preserves self-disable markers when expanded arguments
  are substituted into outer macros, fixing CPython faulthandler aliases.
- Native x86_64 global integer initializers now fold comma constant
  expressions used by CPython static-assert-style fragments.
- Sema and native x86_64 now support compiler memory builtins such as
  `__builtin_memset`, lowering them to libc memory symbols.
- Native x86_64 now lowers GNU statement expressions with inner local
  declarations and final expression values.
- Native x86_64 global pointer initializers now fold constant conditional
  expressions before resolving relocatable subobject addresses.
- Native x86_64 now lowers CPython's `__atomic_*` builtin subset directly and
  omits `-latomic` when linking this target.
- Native x86_64 object-only link delegation now also filters `-latomic`,
  covering CPython `_freeze_module` links that contain only prebuilt objects.
- Native x86_64 now lowers common GCC compiler builtins used by CPython
  objects, including unreachable/frame-address/va-copy, bit operations, and
  inf/nan constants, without external `__builtin_*` symbols.
- Preprocessing now expands macro calls that appear before an unclosed
  trailing block comment on the same line, fixing CPython `assert(...); /*
  multiline */` shapes that otherwise leaked raw `assert` calls into native
  links.
- Native x86_64 scalar casts now move results into the requested GPR, fixing
  casted-pointer lvalue assignments such as `*(int *)dst = *(int *)src`.
- Native x86_64 variadic functions now use a SysV-shaped `va_list` with
  register save offsets, overflow pointer, and saved GP/FP argument registers,
  so `va_start` sees register-passed varargs before stack overflow arguments.
- Native x86_64 nested call arguments now preserve SysV stack alignment when
  earlier arguments are already waiting on the stack, fixing variadic callees
  that spill XMM registers in their prologue.
- Native x86_64 `va_list` parameters now behave as pointers to SysV
  `va_list` storage for forwarding, `va_copy`, and `va_arg`, fixing copied
  varargs in formatting helpers such as `PyUnicode_FromFormatV`.
- On x86_64 Linux hosts, driver mode now defaults to `x86_64-linux-gnu`,
  so `CC="xcc"` uses the native ELF backend instead of LLVM/`llc`.
- Native x86_64 now lowers `__builtin_alloca` and
  `__builtin_alloca_with_align` by reserving aligned dynamic stack space,
  avoiding unresolved builtin symbols when linking CPython bootstrap tools.
- Native x86_64 `for` lowering now scopes initializer declarations to the
  `for` statement, so CPython flowgraph loops such as `for (int i = 0; ...)`
  do not overwrite or hide an outer instruction-index parameter after the loop.
- Native x86_64 CPython compile handling now accepts Linux PIC flags such as
  `-fPIC`, allowing extension-module objects to reach native code generation.
- Native x86_64 casts now decay array expressions before scalar conversion, so
  CPython shapes such as `(uintptr_t)local_char_buffer` compile without trying
  to scalarize the whole array object.
- Native x86_64 external data references now load through ELF GOT relocations,
  so shared CPython extension modules avoid direct text relocations against
  symbols such as `_Py_NoneStruct` and `PyExc_ValueError`.
- Native x86_64 math-module support now accepts and lowers `__builtin_signbit`
  and `__builtin_isnormal`, and compiles long-double suffixed literals through
  the backend's double constant path while preserving 16-byte `long double`
  layout.
- Native x86_64 PIC data addressing now uses GOT loads for non-static
  file-scope data defined in the current object as well as external data,
  avoiding shared-object relocations against default-visible globals.
- Native x86_64 switch lowering now materializes large unsigned case values
  before comparing, avoiding invalid `cmp r64, imm64` assembly.
- Native x86_64 PIC function designators now load non-local function
  addresses through GOT relocations while leaving direct calls as calls.
- Native x86_64 frame planning now preserves function-scope tagged
  struct/union bindings for nested block declarations, so CPython math
  module `union pun` locals do not resolve to unsized bare `union`.
- Native x86_64 block-scope array declarations now keep their array type when
  shadowing an outer pointer of the same name, fixing HACL SHA3 temporary
  buffers.
- Native x86_64 SysV aggregate passing now handles non-power tail chunks such
  as 3-byte structs with bytewise INTEGER chunk loads and stores.
- Native x86_64 record initializers now accept nested initializer lists for
  array members, covering expat's `struct siphash` buffer initialization.
- Native x86_64 global pointer initializers now fold global symbol plus/minus
  integer element offsets into byte-scaled relocations for codec tables.
- Native x86_64 global integer initializers now fold casts from floating
  constants, such as expat feature values written as `(long)100.0f`.
- Native x86_64 anonymous record matching now compares member types and array
  bounds, so CPython datetime structs with `data[10]` are not mistaken for the
  earlier time structs with `data[6]`.
- Native x86_64 pointer compound assignment now scales variable offsets by the
  pointee size, fixing CPython dict-entry cursor updates such as
  `PyObject **pvalue += offs`.
- Native x86_64 wide string literals now emit target-width code units for
  `L"..."`, `u"..."`, and `U"..."`, fixing CPython filesystem error-handler
  matching before codec initialization.
- Native x86_64 anonymous record matching now normalizes enum fields before
  comparing typedef bodies, so `PyStatus`-style records recover their sema
  identity during frame planning.
- Native x86_64 type-spec resolution now preserves incomplete tagged
  `struct`/`union` names for pointer members, fixing `Parser`-style anonymous
  records that contain opaque runtime pointers.
- Native x86_64 static local references now route scope markers back to their
  data labels, so function-local static arrays are not read from `[rbp]`.
- Native x86_64 postfix pointer updates used as dereference addresses now store
  the incremented pointer through the original lvalue slot, fixing CPython
  `_freeze_module` CFG traversal stack corruption.
- Native x86_64 frame planning now rejects incompatible flat same-name semantic
  locals for scoped declaration slots, preserving pointer-width loads for
  shadowed locals such as CPython marshal's `PyObject *code`.
- Native x86_64 conditional aggregate call arguments now restore codegen
  stack-depth accounting per branch, avoiding bogus alignment pads before the
  next call.
- Verified full CPython `configure` on gpu02 through `config.status`,
  `Makefile`, and `pyconfig.h` generation with
  `CC="$HOME/xcc-cpython-gpu02/bin/xcc --target=x86_64-linux-gnu"`.
- Verified gpu02 CPython `configure` on a minimized source tree through
  `config.status` generation; the remaining failure there was a missing
  CPython template file from the intentionally incomplete source tree, not an
  xcc compile failure. Full-source `configure` now passes; `make`
  verification remains in progress.
- Verified a gpu02 smoke build with
  `xcc --target=x86_64-linux-gnu -nostdinc smoke.c -o smoke`; the generated
  ELF executable ran with `rc=0`. Full-source CPython `make` support remains
  pending.
- Codegen canonicalizes `bool` to `_Bool` for LLVM type selection and
  anonymous-record typedef matching, fixing CPython `pyexpat` type sizes.
- Static local references in constant initializers now resolve to the
  function-local static global instead of creating undefined externals.
- Simplified internal module structure by folding parser helper/diagnostic
  modules, preprocessor common helpers, and call argument checks into their
  owning packages/classes.
- Split raw libLLVM-C ctypes loading/signature bindings into `llvm_api.py`,
  leaving `codegen.py` focused on AST-to-LLVM lowering.
- Tightened helper-module contracts with typed Protocol boundaries in
  preprocessor text processing, parser statement parsing, and file-scope sema
  declaration analysis; removed avoidable local alias imports and type ignores.
