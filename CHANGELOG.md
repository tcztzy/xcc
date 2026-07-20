# CHANGELOG

## Current

- B625 separates borrowed intrinsic results from owned allocations in phase
  effect analysis. The post-B624 full Stage 1-to-2 run still reached its
  900.12-second process-group watchdog after 896.91 user seconds with only
  50,397,184-byte maximum RSS, zero swap, 409 source opens, no external tool
  execution, and no Stage 2 artifact. A bounded five-second sample attributed
  82.6% of 3,818 stacks to owner-graph promotion and 16.2% to capture-target
  lookup while the compiler was still lexing. Separately, pointer-shaped
  borrowed intrinsics such as string/tuple indexing were being counted as
  allocations solely from their result type, giving `_PythonLexer._peek` a
  region on every character lookup. V412 preserves a phase for actual scratch
  allocation while propagating no-allocation through borrowed indexing and a
  forwarding caller. Full-slice phase owners fall from 828 to 798. The retained
  hosted Stage 1 builds in 28.14 seconds at 318,685,184-byte maximum RSS; its
  focused borrowed-string program compiles in 0.11 seconds at 47,120,384-byte
  maximum RSS using only `llc` and `cc`, then exits 7. No full post-B625
  Stage 1-to-2 result is claimed.

- B624 adds a semantics-preserving aligned-key fast path to typed native
  dictionary equality. Equal dictionaries built in the same deterministic order
  now compare each key/value pair once; the V410 order-independent search remains
  the fallback whenever aligned keys differ. The B623 full AOT suite passed all
  973 tests in 508.10 seconds, but its first full Stage 1-to-2 run reached the
  900.20-second process-group watchdog with only 67,059,712-byte maximum RSS,
  zero swap, 409 source opens, no external tool execution, and no Stage 2
  artifact. Static analysis shows 864 functions and four allocation-summary
  iterations; the old always-search path performed 1,494,720 same-order key
  comparisons. V411 keeps the different-order native oracle while checking both
  aligned and fallback CFGs. No post-B624 Stage 1-to-2 result is claimed yet.

- B623 restores Python structural equality for typed native dictionaries. The
  LLVM emitter now checks lengths, finds each left key in the right mapping
  independently of insertion order, and recursively compares typed key/value
  payloads; `!=` negates the same result. V410 covers the exact
  `dict[str, tuple[bool, bool]]` shape used by ownership fixed points with
  CPython and native oracles. The retained B623 Stage 1 builds in 28.05 seconds
  at 323,108,864-byte maximum RSS with zero swap. It compiles `return 7` through
  the subset parser in 0.62 seconds at 35,405,824-byte maximum RSS, invokes only
  `llc` and `cc`, and the result exits 7. This removes the pointer-equality
  infinite fixed point exposed after B622; no Stage 1-to-2 claim is made yet.

- B622 adds fail-closed promotion for native tagged `object` graphs. The owner
  barrier now moves the tag box and recursively handles pointer payloads,
  registered tuple/dict layouts, and only the concrete record types actually
  boxed by the module. Static base/union walkers dispatch by the runtime record
  id into a deduplicated exact-layout walker, so both an actual base instance
  and every subclass retain all fields without recursively re-entering the
  static dispatcher; unknown tags, layouts, and record ids remain memory safety
  failures. Built-in `super().__init__` argument evaluation receives a narrow
  region-safe effect matching its emitter, while its generic intrinsic
  classification stays conservative. V409 CPython/native oracles preserve
  string, tuple, actual-base, and subclass values across callee reset. The
  862-function full slice now has 828 owners and 469 fallible owners, covering
  parser, analyzer, binder, named-slice, and lowerer roots. A retained hosted
  Stage 1 build completes in 27.99 seconds at 321,060,864-byte maximum RSS with
  zero swap. Its tiny native CLI reaches emitter effect analysis, where the
  pre-existing pointer-only lowering of structural dict equality prevents the
  fixed point from converging; no Stage 1-to-2 result is claimed yet.

- B621 extends owner-targeted barriers through typed dictionary insertion and
  update, set insertion and update, sequence slice replacement, and lazy module
  containers. Pure builders and removal-only operations keep a separate
  nonretaining proof rather than being mislabeled as generic no-capture
  mutators. V408 CPython/native oracles cover dict assignment/default/update,
  set add/update, list slice replacement, and repeated reads after lazy global
  initialization. Full-slice ownership rises from 270 to 731 functions and
  from 71 to 381 fallible functions; lowerer entry points become phase owners,
  but the named-slice root remains blocked by parse/analyze/bind error chains.
  The post-B620 native-contract Stage 1 baseline built in 27.68 seconds at
  343,474,176-byte maximum RSS with only `llc`/`cc` and no Python dependency;
  B621 hosted full emission uses 311,164,928-byte maximum RSS with zero swap.
  No Stage 1-to-2 run was attempted.

- B620 adds owner-targeted write barriers for statically traversable graphs.
  Record fields, sequence items, and stable sequence append/add/extend stores
  now resolve the exact owner region and move newly reachable allocations
  before its separating mark; grown tuple backing storage follows the same
  lifetime. The lookup is cached per active top-mark/owner pair and invalidated
  on mark, reset, or commit. V407 CPython/native oracles cover capture across
  two nested child regions, string list assignment, record-field assignment,
  and append growth from zero capacity. Full-slice ownership rises from 144 to
  270 functions and from 12 to 71 fallible functions, emitting 271 marks, 145
  failure commits, and 1,733 capture calls. Lower/slice/binder entry functions
  are still excluded; B620 does not claim a bounded Stage 1-to-2 build.

- B619 gives fallible compiler phases an explicit failure-lifetime transfer.
  Propagating an unhandled status removes only the validated top phase mark and
  merges its whole allocation segment into the parent, preserving arbitrary
  error graphs; successful returns still promote their statically typed result
  graph and reset the remaining temporaries. A greatest-fixed-point capture
  proof remains conservative around mutation and admits 12 of 471 fallible
  functions in the full slice, with no lower/slice/binder owner yet. V406 covers
  emitted success/failure control flow, native parent reclamation and preserved
  storage, and non-LIFO rejection. The bounded post-B618 Stage 1-to-2 run that
  motivated this work exited 70 after 280.90 seconds at the unchanged 512 MiB
  allocation guard, with 597,753,856-byte maximum RSS, zero swap, 3,137 source
  opens, no external tool execution, and no Stage 2 artifact. B619 is therefore
  a required lifetime primitive, not a claim that Stage 2 is now bounded.

- B618 makes region-membership lookup local to the current lifetime. Promotion
  now searches only from the allocation head to the top mark and rejects parent,
  global, static, or untracked pointers at that boundary; it no longer performs
  a whole-process allocation lookup followed by a second ancestry walk. V405
  checks the emitted runtime structure and proves with a native nested-region
  oracle that a parent allocation cannot be moved by its child. A focused
  12,000-allocation/12,000-probe comparison improves from 0.725 to 0.434 seconds.

- B617 adds typed owned-result transfer between nested compiler regions. The
  runtime moves an exact current-phase allocation before its mark without
  changing its address; generated type-specific walkers transfer reachable
  string/bytes, tuple, dict, and record storage before the callee reset. Unknown
  layouts, capture-capable functions, and fallible error graphs remain
  conservative. V404 covers outermost promotion plus tracked `realloc`/`free`,
  child-to-parent transfer and parent reclamation, and a CPython/native nested
  tuple graph containing a freshly allocated string. The complete 958-test AOT
  suite passes. A hosted full slice emits 850 functions, 51 owned-result
  functions, 46 promotion helpers, and 108 phase marks. Its bounded native
  Stage 1-to-2 run no longer hit the allocation limit: maximum RSS fell to
  169,164,800 bytes with zero swap. It nevertheless used 298.93 user seconds
  until the 300.21-second process-group watchdog boundary and produced no
  Stage 2. The audit shim produced no log because `DYLD_INSERT_LIBRARIES` was
  inherited through SIP-protected `/usr/bin/time`; no open/exec conclusion is
  drawn from that run.

- B616 extends compiler-derived owned phases to pointer-returning functions only
  when a fixed-point provenance proof shows that every result borrows from an
  input/static value or another proven borrowed return. Fresh, captured, and
  ambiguous pointers, including scalars boxed by the return ABI, remain
  conservative; the focused V403 CPython/native oracle verifies that reset
  preserves the returned pointer. The hosted full AOT slice proves 22 borrowed
  returns and 17 additional phase owners (56 total); 198 emitter/M3 tests and
  the 11 previously failing native-bootstrap oracles pass. Its bounded
  Stage 1-to-2 oracle still exited 70 at the unchanged allocation limit after
  59.84 seconds (58.65 seconds user), with 641,335,296-byte maximum RSS, 3,137
  source opens, no tool execution, and no Stage 2 artifact. Borrowed-result
  phases improved time but did not bound fresh result-graph lifetimes.

- B615 caches positive and negative record-name projections per lowerer and
  replaces repeated `rsplit` tuple allocation with `rfind`. The focused V402
  CPython oracle and 456 relevant AOT tests pass. Its single bounded
  Stage 1-to-2 attempt still exited 70 at the unchanged allocation limit after
  628.95 seconds (63.41 seconds user), with 530,612,224-byte maximum RSS and
  640,942,896-byte peak footprint; it opened 3,137 source paths, executed no
  tool, and produced no Stage 2 artifact.

- B614 makes reachability materialize each record at most once.
  `_lower_named_slice_from_roots` now passes only records not already emitted.
  The CPython oracle produced 10,346 `IrGetField` nodes; 248 AOT tests, lint,
  and type checks pass. Stage 1 has 835 functions, 174 records, and 8,709
  edges, depends only on `libSystem`, and has no Python symbols.

- Revalidated Stage 0 -> Stage 1 after virtual borrowed string locals at
  `52d6395`. The clean no-cache hosted build admitted 65 source units and
  emitted 835 functions, 174 records, 8,709 reachability edges, and 32 lazy
  global-container slots. `_rename_call_target` now contains four string
  concatenations instead of five and four borrowed `startswith` calls. The
  executable reports `xcc-aot 0.2 native-contract`, rejects the CPython parser,
  logs only `llc` and `cc`, and has no Python/libpython dependency. Peak RSS was
  322,633,728 bytes with no swap; source-manifest, normalized-LLVM, and
  executable SHA-256 values are respectively
  `83cdb73d58f295de359e62dbf128e9bdf0231e2688fb6c2ccbec4c1caebf9236`,
  `890cf8746052a71a04bda1ad42b6c9f5c06ebf69637924997037acd583191420`,
  and `b16a402b6f66e149f6f533975eb6fc2ad764ac5a62dea7c22ede8cee523c32a0`.
  The direct audited Stage 1 -> Stage 2 attempt opened repository Python source
  without executing Python or loading libpython, then exited 70 at the fixed
  allocator boundary with 554,434,560-byte peak RSS, no swap, no signal, and no
  Stage 2 artifact; Stage 2 therefore remains incomplete.
- Kept pure concatenated-string locals virtual across multiple borrowing uses
  in one statement. `startswith` compares their parts, `len` sums part lengths,
  and dependency mutation or any later/unknown use forces normal materialization;
  the proof walker itself uses allocation-free scalar counters.
- Extended borrowed `startswith` prefixes across a pure, immediately consumed,
  single-use local assignment. Conservative use analysis keeps multi-use,
  self-referential, effectful, and later-observed concatenations materialized.
- Lowered concatenated `str.startswith` prefixes as borrowed consecutive part
  comparisons. Dynamic f-string components are still evaluated once in order,
  but the native path no longer allocates their combined temporary merely to
  scan it, and offset advancement saturates safely on overflow.
- Made the default test runner and both tox test paths explicitly serial while
  native allocation lifetimes remain incomplete. This closes the remaining
  gate-level concurrency path confirmed by post-reboot panic evidence; explicit
  `--jobs auto` remains available only as an operator-selected mode.
- Revalidated Stage 0 -> Stage 1 after stable comprehension builders at
  `f1cc63d`. The clean no-cache hosted build admitted 65 source units and
  emitted 824 functions, 174 records, 8,627 reachability edges, and 32 lazy
  global-container slots. Its generated comprehension-emitter function calls
  stable append 12 times and full tuple concatenation zero times. The executable
  reports `xcc-aot 0.2 native-contract`, rejects the CPython parser, logs only
  `llc` and `cc`, and has no Python/libpython dependency. Peak RSS was
  332,005,376 bytes with no swap; source-manifest, normalized-LLVM, and
  executable SHA-256 values are respectively
  `bcea1fea01315b051f8005ba0280bbd825dfd8704cb8eb46d13a5b9b17b8b0cd`,
  `197a7a3f74208d10f047823f1858f9662345ed8c415c6a4cea2b527fbcc08729`,
  and `33502d9515184b76161a9df6aa4943a1a690ddaa6f0fe56173b2cbb077770017`.
- Changed eager tuple, list, and set comprehension construction to append each
  boxed value directly to the fresh stable builder handle. Set comprehensions
  retain their membership guard, while all three forms avoid allocating a
  singleton and copying the complete accumulated result on every iteration.
- Revalidated Stage 0 -> Stage 1 after lazy global-container promotion at
  `c66f70b`. The clean no-cache hosted build admitted 65 source units and
  emitted 824 functions, 174 records, 8,627 reachability edges, and 32 lazy
  global-container slots. It reports `xcc-aot 0.2 native-contract`, rejects the
  CPython parser, logs only `llc` and `cc`, and has no Python/libpython Mach-O or
  undefined-symbol dependency. Peak hosted-build RSS was 332,021,760 bytes with
  no swap; source-manifest, normalized-LLVM, and executable SHA-256 values are
  respectively `41479fa814486352f8c189d21e222102131e3eed20030ee425da139e43eb13f4`,
  `283056904c4ab8ad26fa02a2a56655203ee8c802feaa6445069a499a88869c7e`,
  and `6a149c2d3d7d8922b95388b2f757584949c1f46378660446c245f049be27c853`.
- Promoted module-level literal containers to lazily initialized process-stable
  handles. The first access creates an ordinary growable heap-backed handle;
  later reads reuse it, so global identity and alias-visible mutation are
  preserved without rebuilding large literal graphs on every function call.
- Changed recursive call-target reachability discovery to append into one
  root-owned list. It preserves source traversal order and duplicate calls while
  eliminating per-child tuple concatenation and normalization.
- Changed recursive IR record reachability discovery to borrow one root-owned
  mutable accumulator. Type, expression, statement, and branch walkers no
  longer allocate and sort intermediate tuples at every child node; the public
  query normalizes one result after the full traversal.
- Unified slice-global and module-local constant discovery into one pass.
  Retained lowerers now borrow the per-module annotation, string, scalar, and
  container tables whose values already back the shared first-definition view,
  instead of reconstructing equivalent literal IR during preparation.
- Replaced per-module copies of complete lowerer metadata with local-first,
  immutable shared fallback maps. Class, function, alias, annotation, and
  constant resolution preserves module shadowing, global annotations convert
  lazily, and local annotations still hide incompatible shared container
  constants without retaining a project-sized dictionary per lowerer.
- Revalidated Stage 0 -> Stage 1 after stable `set.add` at `95d8fbd`.
  The clean no-cache hosted build admitted 65 source units and emitted 817
  functions, 173 records, and 8,584 reachability edges. The resulting
  `xcc-aot 0.2 native-contract` rejects the CPython parser, logs only `llc` and
  `cc`, and has no Python/libpython Mach-O or undefined-symbol dependency. Peak
  hosted-build RSS was 321,454,080 bytes; the source manifest, normalized LLVM,
  and executable SHA-256 values are respectively
  `2be5fa44ac88410a83c9ab0398f143e5cea94188bfc9f4700c288a44cbb8ee3e`,
  `7ebcd7f3329f750ffea80777a9f5f6ce6ed6fbccb5f97b32d69624862545be2b`,
  and `5c0ce9369336bb9cf748c983ab62d7948b1ec8b5124431b2f244fd940cc2a1bc`.
- Made native `set.add` append a unique item directly to its stable handle.
  Duplicate insertion remains a no-op and aliases observe the same mutation,
  while lowerer global-name collection no longer retains singleton wrappers and
  complete set copies for every discovered name.
- Added a process-stable native cache for all 256 single-byte string values.
  String indexing, string iteration, comprehensions, and `chr` now reuse cached
  immutable values instead of retaining one two-byte allocation per character.
  The runtime oracle verifies stable pointers and unchanged allocation
  accounting across repeated lookup.
- Revalidated Stage 0 -> Stage 1 after compact slice metadata at `2eea81f`.
  The clean no-cache hosted build admitted 65 source units and emitted 817
  functions, 173 records, and 8,584 reachability edges. The resulting
  `xcc-aot 0.2 native-contract` rejects the CPython parser, its logged tools are
  only `llc` and `cc`, and Mach-O/undefined-symbol audits contain no Python or
  libpython dependency. Peak hosted-build RSS was 274,939,904 bytes; the source
  manifest, normalized LLVM, and executable SHA-256 values are respectively
  `d59e8ce23ccdfe89129b94a0b035ca0526fffcb286be0036063137231e516aff`,
  `db0507f4cfc91d0fa54499249318e7ff524ea6ba96e42e2758a3e59b56751219`,
  and `26d5e99655f368ce4a2a86ed8966ebe82614b2219cae34b6945a7e82caf40f05`.
- Split named-slice metadata discovery into compact binder queries. Function
  signatures and class tables no longer retain complete per-module analyses,
  subset summaries are checked once, and alias discovery reuses the sole final
  lowering analysis. A 65-module oracle confirms exact equality with the former
  full-binding results for 5,571 signatures, 305 classes, and 35 aliases.
- Made native dictionary insertion use stable-handle append directly.
  `setdefault` and new-key subscript assignment now allocate only their
  persistent key/value pair instead of a singleton wrapper plus a full dictionary
  concatenation, preserving aliases while bounding growth by live entries.
- Reworked native contiguous list slice assignment to mutate the stable
  tuple-backed handle in place. Bounds remain Python-normalized, capacity grows
  geometrically, and overlap-safe moves cover insertion, deletion, replacement,
  and self-assignment without allocating prefix/suffix/concat temporaries. This
  removes the retained-allocation path that exhausted 512 MiB in `py_ast.walk`
  while Stage 1 resolved the Stage 2 source set.
- Revalidated Stage 0 -> Stage 1 after stable dictionary insertion at
  `056979c`: the clean no-cache hosted build admitted 65 source units and emitted
  812 functions, 173 records, and 8,533 reachability edges. The resulting
  `xcc-aot 0.2 native-contract` rejects the CPython parser, its logged tools are
  only `llc` and `cc`, and Mach-O/undefined-symbol audits contain no Python or
  libpython dependency. Peak hosted-build RSS was 334,626,816 bytes; the source
  manifest, normalized LLVM, and executable SHA-256 values are respectively
  `9a277fef6f00eff04d1a4e17e586bfe7598dd9d8f9e52ce7702ec2347d31d213`,
  `0443a6dce75d2affe29ef16a61849e050db498ac1e3731932fb1d3b7e24b068c`,
  and `393fe9456c760e7c115ae5f43fb07a9b4f69ea48653f6026c786aa3581c0bab9`.
- Added native `set.difference_update` for homogeneous tuple-backed sets. The
  lowerer routes it through alias-visible stable-handle mutation, and LLVM
  emission computes the difference before forwarding the replacement buffer
  into the original handle; mutating set operations remain outside owned-phase
  no-capture proofs.
- Added compiler-derived owned phases without changing Python syntax. A module
  fixed point proves no-capture call summaries, rejects pointer/fallible/unknown
  escape paths, and inserts balanced mark/reset calls only around allocating
  scalar/`None` functions. The real native compiler now contains 71 such phase
  owners; `<math.h>` and `include_next` pass at 187,990,016 and 188,039,168 bytes
  maximum RSS. Removed the `str.startswith` raw-pointer cache so a runtime helper
  classified no-capture cannot retain phase storage after return.
- Added the native phase-arena runtime ABI: nested marks enable provenance
  headers only for phase-owned allocations, reset validates and releases exactly
  the marked segment, and allocation accounting returns to its pre-phase value.
  Runtime-owned chain lookup establishes provenance before header access, stable
  LIFO sentinels preserve nested marks across reallocations, and invalid reset
  order fails before release. Ordinary bounded allocations keep their previous
  low-overhead layout; the real `<math.h>` and `include_next` probes pass at
  190,611,456 and 229,900,288 bytes maximum RSS respectively. Safe
  compiler-inserted boundaries remain the next step.
- Added conservative ownership/liveness analysis for homogeneous tuple
  rebinding. A fresh, non-escaping tuple updated as `value = (*value, item)` now
  grows its stable backing buffer geometrically; aliased values retain immutable
  concat semantics. The two former 512 MiB bootstrap failures now pass without
  raising the limit, with measured maximum RSS around 182 MiB and 219 MiB.
- Replaced tuple-backed inline payload pointers and three million-slot global
  metadata tables with stable runtime handles. Tuple/list/dict/set growth now
  resizes only the owned element buffer through the allocation boundary,
  preserves aliases without forwarding chains, and keeps object-layout metadata
  in the handle. Out-of-range runtime get/set operations cannot access the
  backing buffer.
- Routed generated `malloc` and `calloc` operations through an overflow-checked
  AOT allocation boundary with a 512 MiB cumulative emergency limit and a
  deterministic exit-70 diagnostic. This is crash containment, not completion
  of the required stable-handle and phase-lifetime runtime model.
- Made CPython integration serial by default and rejected parallel
  `--native-aot-cc` validation after two parallel native builds exhausted host
  memory and triggered watchdog kernel panics. Native compiler execution remains
  paused until allocation lifetimes and a controlled OOM path are implemented.
- Completed the approved strong-bootstrap Milestone 8. Native Stage 2 built
  independent cache-free Stage 3-A and Stage 3-B compilers from the same 65-unit
  repository `.py` snapshot under the execution audit boundary. Both builds
  recorded all 3,118 source opens, invoked only `llc` plus the allowlisted system
  linker, linked only `libSystem`, and exposed no Python API symbols.
- Verified Stage 2, Stage 3-A, and Stage 3-B have byte-identical source manifests,
  reachability artifacts, normalized LLVM, exported symbols, and executables.
  Their manifest SHA-256 is `aef31a6b1e1c2fdcd3fe74f775e3ab20a448e3a0db4abfbd5cceed5f9bff131c`,
  normalized-IR SHA-256 is `a9bbae4256ef144fe8a75c889a660511610cc146d293b06bc2cb7217b2085068`,
  and executable SHA-256 is `d574525e0acdfaba0bd4e6312bd6f841eec84dd2b43495ce9b3f0405cee2fae8`.
  Independent compiler/runtime behavior gates also match. This completes T8
  only; the full regression and CPython compatibility gates remain Milestone 9,
  and CPython `configure && make` was not resumed.
- Completed the approved strong-bootstrap Milestone 7. Native Stage 1 built
  `build/aot/stage2-m7-b538/xcc-aot` from a cache-free 65-unit repository
  `.py` snapshot through the project-owned parser. The audited build recorded
  3,118 source opens, 773 functions / 173 records / 8,157 reachability edges,
  and only `llc` plus the allowlisted system linker in its process boundary.
  Stage 2 links only `libSystem`, exposes no Python API symbols, and its LLVM
  contains only qualified owned-parser calls.
- Verified the resulting Stage 2 by having it compile the independent owned
  parser walk fixture from `.py` under the same audit boundary. The fixture
  exits with status 7, its normalized LLVM is byte-identical whether built by
  Stage 1 or Stage 2, and neither build launched or linked Python/libpython.
  This completes T7 only; Stage 2-to-Stage 3 stability remains Milestone 8,
  the full regression suite was not run, and CPython `configure && make` was
  not resumed.
- Completed the approved strong-bootstrap Milestone 6. Stage 0 now builds the
  persisted `build/aot/stage1/xcc-aot` from a clean, no-cache 64-unit source
  snapshot and emits LLVM, normalized IR, a source manifest, 665-function /
  167-record / 7241-edge native reachability evidence, a deterministic native
  tool log, and the executable. Stage 1 reports native mode, rejects the hosted
  CPython parser, links only `libSystem`, exposes no Python API symbols, and
  compiles an independent `.py` fixture through the owned subset parser to a
  program with exit status 7 while invoking only `llc` and `cc`.
- Added the shared `--tool-log` build option to the hosted and native AOT CLIs
  so V378 is checked against the commands actually executed rather than inferred
  from configured option names. Verified Milestone 6 with two independent full
  Stage 0-to-Stage 1 builds, the persisted Stage 1 dependency/symbol audit,
  4/4 native CLI integration tests, 31/31 CLI/admission tests, and lint/type/diff
  gates. This completes T6 only; Stage 1 building Stage 2 remains Milestone 7,
  and CPython `configure && make` was not run.
- Completed the approved strong-bootstrap Milestone 5. The hosted build is now
  rooted at `xcc.aot.cli:main` and emits the real source loader, owned
  lexer/parser, binder, lowerer, IR validator, LLVM emitter, runtime, and native
  tool runner. Its deterministic reachability artifact contains call/type
  reason edges and excludes `ast.parse`, the CPython AST adapter, and the old C
  smoke root. The resulting native compiler reads an independent ordinary
  `.py` file, emits LLVM/normalized IR plus a source manifest, invokes `llc` and
  the system linker, and builds a program with the CPython-matching exit status
  7 without Python or libpython.
- Closed the native-root blockers B450-B470 in AOT-owned code: entry
  qualification and IR validation, lazy conditional-expression CFG, nullable
  record boxing and branch joins, global AST type-marker reachability, f-string
  container inference, cross-call tuple-backed list/set/dict mutation, typed
  dictionary assignment, and deterministic class-owner refinement across the
  64-unit hosted source closure. No non-`src/xcc/aot` compiler source was
  rewritten.
- Verified Milestone 5 with 49/49 reachability/native-CLI tests in 1170.130s,
  83/83 CPython/native runtime oracles, 19 focused CLI/IR/LLVM regressions, the
  exact hosted acceptance build, and lint/type/diff gates. The persisted
  `xcc-aot` contains the required `xcc.aot` symbols, links only `libSystem`, and
  has no Python dynamic or undefined symbols. This completes T5 only; Stage 1
  production and audit remain Milestone 6. CPython `configure && make` was not
  run.
- Completed the approved strong-bootstrap Milestone 4. Fallible native AOT
  functions now use a compositional status/result/error ABI with typed payloads,
  source spans, cross-call propagation, handler ancestry dispatch, rethrow, and
  supported `else`/`finally` behavior. Only the outer native CLI converts an
  uncaught error to stderr and a process exit status.
- Completed the required native runtime semantics for supported tuple/dict,
  string/bytes, path equality, negative indexing, constructors, iteration, and
  `for`/`while` control flow. Break edges now carry the current iteration's SSA
  values into the loop exit, fixing the anonymous-record typedef failure without
  another parser source workaround. The H419/H420 record-member loop workaround
  was retired back to ordinary Python `while True`/`break`.
- Removed the legacy source-to-LLVM special emitter/bodyless leaf boundary, so
  its ordinary Python `try/except` body reaches the generic status ABI. Factory
  raises use their declared exception-record type, conditional expressions
  narrow both branches, and bytes concat/repeat/encode/iteration use their
  length-aware runtime representation.
- Verified Milestone 4 with 389/389 status/runtime/IR/LLVM tests, a direct
  `status-oracle.ll` to arm64 object `llc` gate, lint/type checks, and the complete
  85-test bootstrap module in 4550.733s. The real native smoke, configure-style
  object/link fixture, conditional include/union/anonymous typedef suite, V367
  missing-include diagnostic, and V368 `include_next` object oracle all pass as
  ordinary tests. This completes T4 only; native `xcc.aot` reachability and
  Stage 1 remain Milestone 5/6 work. CPython `configure && make` was not run.
- Completed the approved strong-bootstrap Milestone 3 frontend: the project now
  has a hand-written Python lexer and recursive-descent/Pratt parser that build
  immutable owned AST nodes without `ast.parse`, generated tables, cached AST,
  marker decorators, pragmas, or source directives. The common
  `module.parse_source` path uses this parser; the CPython adapter is explicit
  Stage 0 oracle code only.
- Added exact lexer and parser oracles over all 67 active `src/xcc` files
  (436,377 CPython tokens). Parser comparison covers semantic fields, 1-based
  line/0-based UTF-8 byte spans, end-exclusive extents, and ordered child edges.
  The `parser-oracle` command also verified all 63 native-candidate modules and
  the `xcc.aot.cli` dependency closure with zero differences.
- Enabled hosted `build --parser=subset --no-cache`. The acceptance build
  produced `build/aot/parser/subset-xcc-aot`, a 37 KiB arm64 native CLI shell
  linked only to `libSystem`, with no Python symbols. Its deterministic
  `subset.reachability` file includes `py_lexer`/`py_parser` and excludes all
  hosted parser modules, but explicitly records `native_call_graph=false`:
  this is not Stage 1 and does not satisfy Milestone 5 reachability.
- Verified Milestone 3 with 527/527 fast AOT tests, lint/type gates, and the
  complete 84-test bootstrap module. The latter ran in 1348.607s with exactly
  the frozen B268/V367/V380 status-2 failure and V368 expected failure, and no
  new failure/error. No CPython `configure && make` work or non-`src/xcc/aot`
  compiler-core source change was performed.
- Completed the approved strong-bootstrap Milestone 2 contract: binder and
  lowerer public APIs now consume an immutable project-owned AST, with CPython
  `ast.parse` confined to an explicit Stage 0 adapter. The adapter covers all
  77 owned-node kinds used by active `src/xcc` source with no unsupported
  nodes. This does not implement the project-owned lexer/parser or claim
  Stage 1.
- Added a deterministic source contract that binds parser identity to its
  backend, retains the exact source/AST snapshot it hashes, resolves nested
  imports plus parent packages, records allowed stdlib dependencies, rejects
  unknown/hosted-only dependencies in subset mode, and emits a canonical
  version-1 source/cache manifest. Common rendering is structural and
  CPython-text independent; spans use 0-based UTF-8 byte columns.
- Added hosted/native `xcc-aot build` command contracts, explicit LLVM,
  normalized-IR, manifest, cache, `llc`, assembler, and linker-command options,
  and a real linked native CLI shell. The shell rejects CPython parsing and
  reports subset build dispatch as unavailable until Milestone 5; it is not a
  native AOT compiler. LLVM normalization now changes metadata only and cannot
  mask path-shaped program constants.
- Verified Milestone 2 with 505 fast AOT tests passing, plus the complete
  84-test bootstrap module. The latter retained exactly the frozen
  B268/V367/V380 valid-union failure and V368 expected failure, with no new
  failure/error. Lint and type gates pass. The secondary native C slice is kept
  separate from `xcc.aot` modules so their same-named AST records cannot pollute
  its legacy flat class table; this remains an integration gate, not Stage 1.
- Completed the approved Milestone 1 Stage 0 freeze. The final six-module AOT
  gate ran 508 tests in 505.034s with only the recorded B268/V367/V380 valid
  union status-2 failure and the V368 expected failure; B271 and B272 no longer
  fail. Lint and type gates pass. The stable baseline tag is
  `aot-stage0-m1-20260711`; it does not claim a native AOT Stage 1 or strong
  self-hosting.
- Split the approved Milestone 1 worktree into ten logical commits covering
  strong-bootstrap documents, hosted binder, IR/lowering, emitter/runtime,
  native oracle tooling, the native C integration boundary, three explicitly
  quarantined core-source groups, and bootstrap slicing/gates. The checked
  source-change ledger now maps all 726 non-AOT source hunks across 32 files to
  their owning commit while preserving missing native-oracle status.
- Updated four direct LLVM codegen helper fixtures to pass the explicit
  left/right null-pointer-constant facts added to `_LLVMGen._compare`; the
  initial Milestone 1 codegen baseline exposed the stale helper ABI as B272.
- Began the approved strong-bootstrap Milestone 1 freeze at baseline
  `codex/test-gate-hardening` / `182d9c7` without modifying or staging the
  unrelated OSS application document. The initial six-module Stage 0 AOT gate
  ran 508 tests in 448.383s: one stale source-to-LLVM ABI diagnostic assertion
  was identified as B271, the valid union probe reproduced the known
  `IrRaise -> exit(2)` caught-exception failure covered by B268/V367/V380, and
  the V368 `include_next` probe remained an expected failure. No CPython
  configure blocker work was resumed.
- Corrected the AOT acceptance target to strong self-hosting. The current
  `build/aot/xcc` is a Python-hosted AOT product that runs as a native C
  compiler; it links no libpython, but its emitted graph is rooted at
  `xcc.cc_driver`, contains no `xcc.aot` compiler definitions, and the hosted
  AOT frontend still uses `ast.parse`. It therefore does not yet qualify as a
  native AOT compiler or Stage 1. Added an independent `specs/aot-python.md`, a
  current-state gap/source-change audit, a project-owned Python subset frontend
  architecture, and a Stage 0 -> 1 -> 2 -> 3 implementation plan. Native C and
  CPython `configure && make` checks are now explicitly final secondary gates.
- Advanced the native AOT bootstrap driver through the autoconf executable-run
  probe used after "C compiler works" checks. The rebuilt `build/aot/xcc`
  compiles, links, and runs the `FILE *f = fopen("conftest.out", "w");
  if (!f) return 1; return ferror(f) || fclose(f) != 0;` probe with run
  status 0. The fixes keep source Python ordinary while making bootstrap-hot
  shapes native-stable: LLVM codegen now avoids side-effect conditional
  expressions for no-else `if` blocks, scans tuple-backed local dictionaries by
  key/value pairs instead of `name in dict`, casts file-scope analyzer Protocol
  receivers to the concrete `Analyzer` for field access, scans string-literal
  quotes without `break`-carried state, and emits native string globals with an
  explicit NUL terminator. Remaining native risks include noisy
  `Duplicate definition: union` stdout from `<stdio.h>` and a separate pointer
  equality crash for forms such as `int *x; return x == 0;`.
- Advanced the native AOT CPython configure path to the first executable-run
  probe after `configure` reports that the C compiler works. The latest
  blocker was the autoconf `if (!f)` / `ferror(f) || fclose(f) != 0` probe:
  native AOT did not recognize unary `!`, lost parent scopes created through
  `Scope(parent)`, and could lose declaration statements appended immediately
  before a `break` edge. Parser unary operator recognition now uses an
  explicit predicate, sema child scopes use `Scope.child()` plus iterative
  parent lookup, and declaration-list parsing avoids the append-then-break
  shape. Focused regressions cover those strict-subset source shapes; the
  formal native rebuild and full CPython native-AOT gate remain pending.
- Advanced the native AOT record-type path past the earlier incomplete-record
  false positives in system headers. File-scope analyzer Protocol calls are now
  rewritten to the concrete `Analyzer` methods, record-body metadata is
  preserved across parser `TypeSpec` rewrites, record tags use native-stable
  string dictionary keys, and bootstrap-critical record/void checks avoid
  loop state that is only observed after a `break` edge. The generated native
  driver now accepts opaque `struct *` parameters/returns, rejects true opaque
  by-value declarations with the expected incomplete diagnostics, accepts a
  defined record by-value prototype as `declare i32 @f({ i32 })`, accepts
  record `void *` members, and compiles a standalone `<stdio.h>` probe to an
  object without the previous incomplete or void-member diagnostics.
- Advanced the native AOT system-header path past the earlier union,
  trailing block-comment include, lexer block-comment, typedef lookup,
  function-pointer field, raw LLVM pointer-array, and native LLVM type
  declarator crashes. The native bootstrap driver now rebuilds and preserves
  pointer declarators in LLVM prototypes: function-pointer parameters,
  `void *` parameters, array-parameter decay, and pointer return types now emit
  LLVM `ptr` instead of falling back to scalar base types. The root cause was
  `_LLVMGen._type_to_llvm()` relying on `reversed(ops)`, which native AOT did
  not execute for tuple-backed declarator ops; it now uses an explicit reverse
  index loop. A standalone native `<stdio.h>` probe now produces an object and
  emits `fread(ptr, i64, i64, ptr)`/`fwrite(ptr, i64, i64, ptr)`, while still
  printing repeated incomplete-type diagnostics that need a follow-up
  diagnostic/error-propagation slice.
- Advanced the native AOT CPython validation path through the earlier
  system-header conditional/include-guard blocker. The bootstrap-reachable
  preprocessor now returns AOT-updated conditional stacks explicitly, avoids
  dynamic tuple slicing for `#endif` pop, records native no-callback macro
  definitions, checks tuple-backed macro dictionaries through `dict.get()`,
  uses a small no-callback include-guard detector for guarded recursive
  includes, and initializes a minimal native predefined macro table for
  bootstrap preprocessing. The native regression now compiles a self-recursive
  guarded header and expands `__PTRDIFF_TYPE__` without the CPython runtime.
  The standalone native `<stdio.h>` probe has moved past the previous
  `Unexpected #else/#endif`, include-cycle, architecture, and builtin type
  blockers; it is now blocked later by Apple SDK `union` declarations and
  repeated unterminated block-comment diagnostics before the native parser
  crashes.
- Added a CPython build-script option that builds native AOT `xcc` first and
  uses that executable as `CC` for `configure && make` validation.
- Extended the native AOT bootstrap driver to accept CPython configure-style
  compile and object-link commands without invoking the Python runtime. The
  native path now accepts `-I`/`-D`/`-U` joined or separated operands,
  `-std=c11`, `-std=gnu11`, rejects unknown frontend flags, and can link an
  existing `.o` input to an executable.
- Added a broad real compiler-path bootstrap LLVM regression that writes
  `build/aot/probes/bootstrap-real-path.ll` and verifies the generated module
  still includes native `main`, `_aot_compile_source_path_to_object()`,
  `frontend._aot_compile_source_unchecked()`, and `_LLVMGen.generate()`. The
  broad LLVM now compiles through `/opt/homebrew/opt/llvm/bin/llc` to
  `build/aot/probes/bootstrap-real-path.o`, and the real native bootstrap smoke
  still builds `build/aot/xcc-smoke` and compiles/links a simple C translation
  unit without the CPython runtime.
- Replaced the native bootstrap source-to-LLVM fast path with a direct call to
  the real `frontend -> sema -> codegen` AOT path. The bootstrap source graph
  now pins `_aot_compile_source_to_llvm_ir_unchecked()`,
  `frontend._aot_compile_source_unchecked()`, `codegen.generate_llvm_ir()`, and
  `_LLVMGen.generate()`, and the emitted native wrapper no longer hard-codes
  `conftest.c`, `#include <...>`, or fixed smoke `main` LLVM.
- Added an AOT source-contract regression gate that rejects `from __future__
  import annotations` and marker-style decorators while keeping width aliases
  as ordinary Python-visible names.
- Advanced the Milestone 6 native bootstrap path through LLVM module
  generation. AOT construction of `codegen._LLVMGen` now initializes the
  runtime LLVM context, module, and builder handles through LLVM C API
  intrinsics instead of defaulting record fields to zero. Native bootstrap
  build now produces `build/aot/xcc`, and that generated executable can compile
  a simple C translation unit with `build/aot/xcc -c ... -o ...` without the
  CPython runtime.
- Advanced the Milestone 6 broad source-to-LLVM slice beyond the previous
  parser/sema alias blockers. The lowerer/emitter/runtime now cover `len(str)`
  via `strlen`, tuple-backed `range(...)`, `reversed(...)`, and `pop()`, tuple
  narrowing from union records such as `int | FunctionParams`, branch type
  merge suppression for `continue`/`break`/`return`/`raise` paths, starred
  tuple-backed container literals, one-argument `dict/list/set/frozenset`
  constructors, dict subscript value typing distinct from optional `.get()`,
  property getter attribute access, nested tuple `for` targets through a
  temporary unpack prelude, and a temporary tuple-backed `dict.setdefault`
  lowering. The core slice renamer now resolves package `__init__.py` imports,
  relative module aliases, direct imported function aliases, and module-level
  assigned helper aliases such as `_parse_directive = _text._parse_directive`
  to qualified slice targets. LLVM text emission now joins `if` assignments
  with real phi values and narrows tuple aliases such as `FunctionDeclarator`
  from record unions before tuple getitem. Parser/preprocessor sources now
  avoid several optional-local AOT traps while remaining ordinary CPython,
  including alignment comparisons, generic default diagnostics, complex
  function declarator capture, and preprocessor line splitting. The expanded
  broad unchecked probe now includes parser, preprocessor, sema, codegen, and
  type modules and compiles through `/opt/homebrew/opt/llvm/bin/llc`:
  `build/aot/probes/broad-unchecked-expanded.ll` lowers and emits 882
  functions, 88 records, and 62,588 LLVM lines, producing
  `build/aot/probes/broad-unchecked-expanded.o`. This slice also adds
  loop-carried `for` assignment phis, straight-line emission for lowered
  `IrIf(True, ...)` blocks, typed `str(int)`/record `__str__` lowering,
  optional-string `len(...)`, `Path.is_file()`, cross-module aliases and
  global container annotations, and source-shape cleanups for reachable
  comprehensions, generator expressions, optional tuple scores, and
  branch-local temporary names.
- Advanced the Milestone 6 source-to-LLVM AOT slice deeper into `codegen.py`.
  AOT lowering now covers signed Python integer floor division/modulo,
  shifts/bitwise ops, `try/finally` and normal-path `except CodegenError` /
  `except Exception`, two-argument integer `min`/`max`, `range(...)`,
  `chr(...)`, `float(...)`, `float.fromhex(...)`, `str.find(...)`,
  `str.split(...)`, `str.endswith(...)`, `str.ljust(...)`, `str.rstrip(...)`,
  `int.to_bytes(...)`, `bytes(...)`, `id(...)`, `zip(..., strict=True)`,
  tuple-backed `dict.items()`, empty container constructors, `tuple(x)`
  identity conversion, tuple-backed `set.add()`/`list.append()` item typing,
  list/generator-comprehension expected-type preservation, optional
  tuple-backed `X | None` annotations, attribute-aware `isinstance(...)`
  narrowing, `is not None` narrowing in `if`/`if` expressions, fallthrough
  narrowing after exiting `not isinstance(...)` guards, and common-field access
  across record unions.
  Codegen source now avoids several bootstrap-hostile dynamic shapes with
  CPython-equivalent explicit branches or annotations: callable/dict dispatch
  in base type and size helpers, generator `max(...)`, union storage key
  callbacks, small local lookup dicts, starred list literals, untyped optional
  symbol lookups, compound operator dictionaries, nested helper functions,
  subscript-target mutating calls, non-empty dict literals, bytearray-backed
  constant assembly, dead `_term` writes, and Optional if-expression field
  access; AOT lowering also supports tuple-of-class `isinstance` narrowing for
  common record-field access. The broader source-to-LLVM unchecked slice from
  `xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked` now lowers to AOT IR
  successfully, currently covering 239 functions and 62 records. LLVM text
  emission and runtime support now cover the newly reached `str.ljust(...)`,
  `str.rstrip(...)`, `str * int`, tuple concatenation/repetition,
  `bytes(...)`, `int.to_bytes(...)`, `id(...)`, and `ord(...)` intrinsics, with
  native smoke coverage for observable string/byte/id paths.
  The same unchecked slice now emits textual LLVM IR end-to-end, currently
  producing 19,176 LLVM lines for those 239 functions and 62 records. The
  emitter/lowerer now handles Python value-semantics `and`/`or` for non-bool
  results, tuple-backed dictionary subscripts, `reversed(tuple)` element type
  preservation, tuple destructuring over homogeneous/opaque runtime tuples,
  object-to-scalar/string/tuple narrowing at use sites, non-`i64` tuple indexes,
  string ordering via `strcmp`, tuple-prefix `str.startswith(...)`, and record
  union field-owner selection. The current broad `llc` probe reaches
  `xcc.codegen._LLVMGen._const_from_bytes` and fails because `for byte in chunk`
  still binds the item as a boxed pointer before an integer shift; the Milestone
  6 implementation plan now records that blocker as the next TDD slice. This is
  textual emission progress only; native execution correctness, length-aware
  bytes semantics, and full runtime object tagging remain future bootstrap work.
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
- Added LLVM emission for lowered tuple length checks. Ordinary lowered Python
  expressions such as `len(argv) != 5` now call `__xcc_aot_tuple_len()` and
  compare an `int64` result instead of treating `len()` as a dynamic pointer
  call.
- Reshaped the AOT smoke compiler helper body so its paths and helper results
  are ordinary annotated Python locals. The body now lowers and emits through
  the generic AOT path without `Path(...)` or `str(...)` bridge calls, while
  preserving the CPython smoke compiler behavior.
- Switched the bootstrap smoke compiler from a native-special LLVM shell to its
  generic lowered Python body. The bootstrap slice now discovers the helper
  calls from `_aot_compile_smoke_source_to_object()` itself and emits ordinary
  tuple length/indexing, branching, and project helper calls.
- Added a project-owned `_aot_compile_source_to_llvm_ir()` boundary for the
  bootstrap smoke compiler. Under CPython it now runs the real frontend and
  LLVM backend for the source text, while the native AOT path temporarily
  specializes that helper as a smoke-only leaf that calls the existing smoke
  source validator and fixed smoke IR helper. The smoke compiler body now calls
  this source-to-LLVM boundary instead of directly validating the fixed source
  and selecting fixed LLVM text.
- Split the source-to-LLVM boundary into an exception-handling wrapper and a
  lowerable `_aot_compile_source_to_llvm_ir_unchecked()` helper whose ordinary
  body directly calls `compile_source()` and `generate_llvm_ir()`. AOT lowering
  now treats imported project call names as valid globals, rewrites
  `from xcc... import ...` calls to fully qualified slice targets, and preserves
  keyword argument values in lowered calls, preparing the bootstrap path to pull
  the real frontend/backend implementation behind the current smoke-only native
  leaf.
- Split the frontend success path into a lowerable
  `_aot_compile_source_unchecked()` helper that exposes the ordinary
  `normalize_options()`, `preprocess_source()`, `lex()`, `parse()`, `analyze()`,
  and `FrontendResult(...)` pipeline without changing `compile_source()`'s
  diagnostic wrappers. The source-to-LLVM unchecked helper now calls that
  frontend success helper before `generate_llvm_ir()`, while the public
  source-to-LLVM wrapper still converts frontend/backend failures to an empty
  string for the current smoke compiler bridge.
- Extended AOT lowering for admitted container annotations by mapping
  `dict[...]`, `set[...]`, `frozenset[...]`, `Iterable[...]`, and
  `Sequence[...]` to the existing tuple-backed opaque runtime shape. This lets
  the cross-module frontend success-path slice get past `SemaUnit`'s existing
  `dict[...]` and `set[...]` fields.
- Added AOT IR, lowering, slice discovery, and LLVM text emission for ordinary
  `while` loops. LLVM emission now gives loop-carried locals header phi values
  and emits integer ordering comparisons for lowered `<`, `<=`, `>`, and `>=`
  predicates. The cross-module frontend success-path slice now advances past
  `xcc.lexer.lex()`'s loop shape.
- Added AOT lowering and LLVM emission for enum member constants such as
  `TokenKind.EOF`, using stable per-module constant pointers for comparisons.
  The AOT type binder now also infers ordinary instance fields assigned in
  `__init__`, allowing lowered methods to read fields such as `self._line`
  without adding class-level annotations. Loop control now lowers and emits
  `break` and `continue` for `while` and tuple-backed `for` loops. The
  cross-module frontend success-path slice now advances through enum constants,
  lexer instance fields, and loop control.
- Added AOT lowering, LLVM emission, and runtime support for existing
  `str.startswith(prefix[, start])` calls, plus lowering for integer
  `+=`/`-=`/`*=` assignments to local names and instance fields. The
  cross-module frontend success-path slice now advances past
  `self._source.startswith(...)` and lexer index/column increments; the next
  observed blocker is the existing `NoReturn` annotation on `Lexer._error()`.
- Added AOT lowering for existing `NoReturn` annotations, no-argument string
  predicates (`isalpha`, `isdigit`, `isalnum`, `isspace`), signature-aware
  project method return/argument types, target-aware assignment value lowering,
  literal assignment inference, `int(text, base)` parsing, and chained
  comparisons. LLVM emission now lowers the string predicates and integer parse
  calls through runtime helpers. The cross-module frontend success-path slice
  now advances through lexer UCN parsing and stops at the existing
  `HEX_FLOAT_RE.fullmatch(...)` runtime regex call in number classification.
- Replaced lexer number-classification runtime regex matching with ordinary
  scanner helpers and reshaped block-comment scanning away from `while ...
  else`. The frontend success-path slice now lowers through lexer number
  classification and comment skipping without runtime regex or `while else`.
  The broader source-to-LLVM unchecked slice now advances into `codegen.py`.
- Split codegen's LLVM module printing behind a typed
  `_llvm_print_module_to_string(module: int) -> str` helper and registered that
  helper as an explicit AOT native LLVM-C leaf. Tuple-backed container
  annotations now retain homogeneous element types for `for` target binding,
  allowing loops over fields such as `TranslationUnit.functions` to bind
  elements as project records. The broader source-to-LLVM unchecked slice now
  advances past `_LLVMGen.generate()` and stops at the existing
  `self._sema.functions.get(...)` dictionary lookup/optional `FunctionSymbol`
  boundary in `codegen.py`.
- Added AOT lowering for existing `dict[str, T].get(key)` calls over the
  tuple-backed container shape, plus simple optional-record narrowing after
  `if value is None: return` guards. Empty `{}` literals now lower as empty
  tuple-backed containers when the expected type is a supported dict shape. The
  broader source-to-LLVM unchecked slice now advances past
  `self._sema.functions.get(...)` and stops at the existing
  `enumerate(real_params)` loop in `codegen.py`.
- Added AOT lowering for existing `enumerate(iterable)` loops and subscript
  assignment statements such as `param_ts[i] = lt`. LLVM text emission now
  treats enumerate loops as ordinary tuple-backed loops with the loop index
  bound to the first target, and emits pointer stores for lowered subscript
  assignment. The broader source-to-LLVM unchecked slice now advances past the
  `enumerate(real_params)` loop and stops at the existing `c.FunctionType(...)`
  LLVM-C receiver call in `codegen.py`.
- Added AOT lowering for the existing `llvm()` API handle pattern and
  `c.FunctionType(...)` LLVM-C receiver call shape, plus direct LLVM text
  emission for `LLVMFunctionType`. Existing `str.encode()` calls now lower as
  C-string identity values, and bytes literals such as `b"entry"` lower as AOT
  string constants for LLVM-C names. The broader source-to-LLVM unchecked slice
  now advances past `c.FunctionType(...)`, `func.name.encode()`, and
  `c.AppendBasicBlock(fn, b"entry")`; the next observed blocker is
  `symbol.type_` after `isinstance(symbol, VarSymbol)` in `codegen.py`.
- Added AOT lowering for `isinstance(...)` branch narrowing over union/base
  record types, optional attribute guards (`is not None` and truthy checks),
  class-level integer constants, Python float literals, negative indexes,
  unary integer `+`, `-`, and `~`, `int(bool)` coercion, tuple-backed `pop()`,
  and `pass` statements. Core slice lowering now also injects cross-module
  method signatures. The broader source-to-LLVM unchecked slice now advances
  past `symbol.type_`, `self._locals[-1]`, `LLVMTypeKind.POINTER`,
  `c.ConstReal(..., 0.0)`, `stmt.statements`, `self._locals.pop()`,
  `pass`, `_eval_case_val` unary operators, and optional `self._func_sym` /
  `self._sema.file_scope` guards; the next observed blocker is `left // right`
  in `codegen.py`.
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
- Native AOT bootstrap now compiles C integer literal return expressions and
  basic binary arithmetic such as `return 6 * 3;` without looping, crashing, or
  losing literal values. Parser operator checks avoid tuple-parameter
  iteration, sema scalar type checks avoid tuple structural equality, typemap
  required lookups reuse native-safe dictionary scanning, and LLVM codegen
  parses C integer literals with an explicit digit scanner.
