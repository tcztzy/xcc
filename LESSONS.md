# Lessons

- Parent-package source resolution can legitimately pull two compiler families
  with the same short class name into one hosted source set. Keep the
  deterministic class owner and its refined metadata coupled; filtering the
  manifest or rewriting a field access only hides the flat-table inconsistency.
- A tuple-backed mutable container cannot implement Python alias semantics by
  returning a replacement allocation and rebinding only the callee local.
  Mutations need in-place storage or a runtime forwarding identity that every
  length/get/set path resolves, with CPython/native cross-call alias oracles.
- Reachable compiler symbols and valid top-level LLVM do not prove that a native
  compiler works. Compile an independent `.py` fixture with the produced binary
  and run the result; this exposed tagged f-string list elements and invisible
  callee mutations only after the full compiler itself linked successfully.
- A Python lexer oracle must compare token text and end-exclusive UTF-8 byte
  spans, not only token kinds. Guard an empty EOF sentinel before string
  membership tests: in Python, `"" in "chars"` is true and can silently accept
  a trailing continuation or take the wrong numeric branch.
- Exact AST span parity needs both semantic node spans and nonsemantic grouping
  extents. Parentheses do not change a child node's own span, but they do change
  the enclosing expression or statement extent; keep that information outside
  the immutable semantic AST and prefer the outermost grouping record.
- A function-local hosted import is still visible to conservative static source
  closure. Moving `ast.parse` behind a lazy import does not make it unreachable;
  the common parse boundary itself must use the owned parser, with hosted
  unsupported-form tests constructing oracle ASTs explicitly.
- A subset source-closure report is useful Milestone 3 evidence, but it is not a
  native call graph. Label that boundary in the artifact
  (`native_call_graph=false`) until the emitted compiler actually reaches source
  loading, parser, binder, lowerer, emitter, runtime, and tool spawning.
- A source manifest must describe the exact bytes and owned AST passed to the
  compiler. Hashing one read and then rereading/reparsing the entry leaves a
  race in which the manifest and artifact can describe different snapshots.
- Project-owned AST structure cannot depend on adapter-only mutation or
  CPython `ast.unparse` text. Make spans and child edges ordinary constructor
  inputs, keep child sequences immutable, and render every semantic key or
  deterministic diagnostic structurally.
- A mocked tool-runner assertion does not prove a native CLI links. Lower and
  emit the real entry in a focused test, then run the planned `llc`/link command;
  this exposed both an omitted helper definition and an i64/int32 loop compare.
- Deterministic IR normalization must be syntax-aware enough to distinguish
  metadata from program constants. Replacing an absolute root across the whole
  LLVM file can hide a real Stage 2/3 semantic difference.
- Freeze source columns before writing the project lexer: CPython AST columns
  are 0-based UTF-8 byte offsets with end-exclusive ends, while
  `SyntaxError.offset` is a 1-based character offset and needs normalization.
- A native artifact and an all-source hosted admission pass do not prove strong
  self-hosting. The acceptance gate must show a native compiler actually reads
  `.py`, runs its own parser/binder/lowerer/emitter, builds the next native
  stage without Python, and repeats to a stable Stage 3.
- When the documented Python subset includes a construct, rewriting compiler
  core source to avoid that construct hides lowerer/runtime debt. Fix the
  AOT-owned semantics first; allow a core rewrite only after an explicit subset
  exclusion and CPython/native behavioral oracles.
- Tuple-backed dictionaries in native AOT are sequences of key/value pairs.
  Python `name in dict` can lower as tuple-element membership and compare the
  key against the whole pair, so use `.get()` only when zero is not a meaningful
  value; otherwise scan `for key, value in dict.items()` explicitly.
- Protocol casts can be runtime no-ops but still important AOT type evidence.
  If native code accesses fields through a Protocol-typed parameter, cast to
  the concrete implementation before field access so record layout offsets come
  from the concrete type, not the Protocol stub.
- Avoid `value = ...; break` when the value is consumed after the loop in
  bootstrap-native code. The AOT loop phi can keep the pre-break value; express
  scans as a loop condition (`while qpos < 0 and index < len(raw)`) or return
  directly from the found branch.
- Native AOT currently represents `bytes` as C strings in several lowering
  paths, so `len(bytes_with_trailing_nul)` can become `strlen(...)` and exclude
  the final NUL. When creating LLVM string constants, pass the non-NUL payload
  length to `ConstString(..., DontNull=False)` and size the global as
  `payload_len + 1`.
- A source-shape fix can be present in native LLVM and still leave a deeper
  backend crash. The pointer/null compare path now has a `ConstNull` branch,
  but `int *x; return x == 0;` still crashes in the native compiler; keep such
  cases as explicit follow-up probes instead of assuming a source-shape
  regression proves runtime success.
- Native AOT constructor lowering currently cannot be trusted to pass
  positional arguments into bootstrap objects. When a field such as
  `Scope._parent` is semantically required, use an explicit helper like
  `Scope.child()` that allocates the object and assigns the field directly.
- Avoid `while True` loops that append semantic state and then immediately
  `break` when native code consumes the appended values after the loop. Use an
  explicit `more_*` loop condition so the loop exit does not also carry the
  last semantic mutation.
- Parser operator recognition in bootstrap-hot paths should use direct
  `_check_punct()` predicates rather than scanning an operator tuple into a
  flag that is read after `break`. This keeps unary forms such as `!f` visible
  to native AOT without adding syntax.
- Protocol-typed helper calls lower to Protocol stubs unless the AOT slice
  rewrites them to the concrete receiver type. For bootstrap helpers such as
  `_FileScopeAnalyzer`, map every reachable protocol method to
  `Analyzer.<method>` or side-effecting sema calls can silently become no-ops.
- Avoid assigning loop-carried state immediately before `break` when native AOT
  observes that state after the loop. Prefer an early return or a loop
  condition that carries the value explicitly; otherwise helpers like
  `_is_invalid_void_object_type()` can lose a detected pointer op on the break
  edge.
- Tuple-valued dictionary keys are risky in bootstrap-native lookup paths
  until native dict equality is fully CPython-compatible. For record tag keys,
  concatenate the stable string parts into one key instead of storing
  `(kind, tag)` tuples.
- AOT tuple-backed dictionaries do not make `name in dict` equivalent to
  CPython dictionary-key membership. In bootstrap hot paths, use `.get(name)`
  for non-null object values or explicitly scan key/value pairs when zero is a
  meaningful value.
- Avoid loop-carried "closed flag plus break" state in AOT hot paths. A direct
  loop condition plus post-loop EOF/error check lowers more reliably than a
  mutable flag whose value is assigned before `break`.
- Native no-callback preprocessor include parsing must strip closed block
  comments around header operands. `#include "x.h" /* self */` should parse as
  the same guarded include target as `#include "x.h"`.
- Do not rely on dataclass `__post_init__` to normalize legacy fields in native
  AOT objects. If code can see both `pointer_depth` and `declarator_ops`, add
  an explicit helper such as `type_spec_declarator_ops()` or
  `type_declarator_ops()` and use it at semantic/codegen boundaries.
- Avoid tuple multiplication/repetition for declarator operator construction in
  bootstrap-reachable parser code. Build pointer-op tuples with an explicit
  loop so native AOT does not depend on `@__xcc_aot_tuple_repeat` for type
  correctness.
- Raw C pointer arrays returned by LLVM helper leaves must not be mutated via
  Python subscript assignment in native AOT. Collect values in a Python list or
  tuple-backed sequence and call `ptr_array(values)` once, or add a dedicated
  raw-array setter.
- Do not rely on `reversed(tuple_ops)` for bootstrap-critical declarator
  lowering. Native AOT can skip tuple-backed reversed iteration, leaving LLVM
  type construction to fall back to scalar base types; use an explicit reverse
  index loop when pointer/array/function ops determine correctness.
- Native AOT object construction currently allocates record fields directly and
  does not run ordinary `__init__` side effects. Bootstrap objects whose
  constructors populate dictionaries or external handles, such as
  `_Preprocessor._macros`, need either a native-specific initialization wrapper
  or general constructor lowering before downstream code can rely on those
  fields.
- Bootstrap-reachable code should avoid negative string indexes until AOT
  lowering has a dedicated string-index normalization path. In native bootstrap
  LLVM, `operand[-1]` became a raw pointer `-1` access and broke system-header
  `#include <...>` parsing; use `operand[len(operand) - 1]` in strict-subset
  code when the tail character is needed.
- AOT record construction must account for classes whose `__init__` performs
  runtime side effects. Direct field-by-field allocation is fine for plain
  records, but bootstrap objects such as `_LLVMGen` need constructor lowering
  that recreates handle initialization; otherwise fields like LLVM module
  pointers silently default to zero and fail much later at a native boundary.
- Entry-driven AOT slice call graphs must canonicalize package `__init__.py`
  imports before dependency discovery. A call imported as
  `from xcc.parser import parse` needs to target `xcc.parser.__init__.parse`
  when the source file is `parser/__init__.py`; otherwise the caller emits an
  unresolved package-level symbol and the real callee is never lowered.
- Entry-driven AOT slice call graphs must also canonicalize module-level
  function alias assignments, not only import statements. A helper binding such
  as `_parse_directive = _text._parse_directive` needs the same qualified
  target and signature as a direct `_text._parse_directive(...)` call, or the
  lowered caller will retain an unbound local helper name.
- For bootstrap-reachable CPython source, avoid carrying structured optional
  temporaries as `tuple[...] | None` or `Token | None` when a bool plus
  non-optional fields expresses the same state. The current AOT emitter can
  narrow pointer-shaped values at use sites, but `None`-initialized record or
  tuple fields can otherwise leak through casts and break field access or
  tuple getitem emission.
- AOT type narrowing from an `if` branch should only merge back into the
  following path when that branch can fall through. Branches ending in
  `continue`, `break`, `return`, or `raise` must not leak narrowed names such
  as `value: int` into later sibling branches that may need to narrow the same
  variable to a tuple-backed union arm.
- Bootstrap AOT helpers should not compare against module-level string
  constants until the lowerer supports those constants as runtime values. In
  the current lowering path, an uppercase global such as `_AOT_SMOKE_SOURCE`
  can become a default null pointer in LLVM; use a local string literal or add
  explicit global-constant lowering before relying on that pattern.
- Native AOT error fixtures should return a deterministic message/status pair,
  not try to mimic Python tracebacks. For early self-hosting oracles, a normal
  Python helper that returns `str(exc)` plus a native wrapper status code is a
  stable comparison surface while exception lowering is still out of scope.
- For AOT oracle fixtures, prefer ordinary CPython helper functions as stable
  comparison surfaces before adding native-specialized leaves. A helper such
  as `summarize_tokens()` keeps the project useful as plain Python while the
  AOT runtime incrementally learns just enough scanning/rendering behavior for
  the next native fixture.
- Entry-driven AOT lowering has to filter both functions and records. Skipping
  unrelated function bodies avoids unsupported statements, but unrelated record
  layouts can still fail lowering, as with lexer-only smoke tests that need
  `translate_source` but not `Token.kind: Enum`. Derive required records from
  the wrapper and lowered IR instead of lowering every class in the module.
- AOT core native oracle tests should prune from the fixture wrapper before
  LLVM emission. Whole-module lowered output can contain source-reachable but
  fixture-unexecuted helpers such as generator expressions; namespace
  same-module calls first, then treat native-specialized functions as leaf
  symbols so the oracle validates the intended entry behavior instead of
  failing on unrelated lowered helpers.
- Treat the real CPython build gate as an isolation problem as well as a
  compiler problem. If the default CPython checkout has ignored in-source
  artifacts, do not clean or reuse it for validation; clone a fresh temporary
  tree and run the same `configure && make -j8` gate there so the result is
  repeatable and does not modify the user's working copy.
- Treat 100% line coverage and 100% branch coverage as separate gates when
  `coverage.run.branch = true`. After AArch64 line closure, `tox -e py311`
  reported 0 missed statements but still only 99.57% combined coverage because
  branch partials remain in AArch64, generic LLVM codegen, and x86_64. Do not
  call the coverage goal complete until both statement misses and branch
  partials are closed or explicitly justified.
- x86_64 backend missing-line closure is fastest when each unreachable-looking
  line is first challenged with a real helper probe. Use narrowly scoped
  synthetic `Type` subclasses and monkeypatches to cover valid defensive
  behavior, but prefer a targeted `# pragma: no cover` only after the local
  invariant proves the branch cannot fire, such as mutually exclusive
  `TypeSpec` guards or range/min chunk-size bounds.
- AArch64 record-layout and ABI-classification coverage moves fastest when
  public lowering tests cover real syntax like `__func__`, while direct helper
  probes cover impossible or diagnostic-only branches such as unsized
  bitfields, HFA rejection, flexible-array fallbacks, and invalid
  short-circuit operators. Always compare JSON missing-line deltas before
  raising the ratchet, because some helper probes also cover shared layout
  fallbacks such as `_member_align`.
- AArch64 builtin and atomic coverage should pair public-path inline-lowering
  tests with direct helper probes for arity and diagnostic branches. The public
  tests prove the compiler emits real Darwin AArch64 text without external
  symbols, while helper probes cheaply cover signed-width atomic variants and
  fallback returns that valid source rarely exercises.
- x86_64 global-initializer coverage is most efficient as a compact helper
  sweep over real record definitions plus narrowly scoped monkeypatches for
  impossible sizing failures. Keep public source tests for normal lowering, but
  use direct helper probes for diagnostic-only branches and verify the exact
  missing-line drop before raising the total ratchet.
- x86_64 variadic and floating-binary helper coverage can stay under a few
  milliseconds by using a real frontend fixture for sema state, then direct
  AST probes for guard-only paths. Check the coverage JSON for the exact
  missing-line deltas before moving the ratchet, because public source tests
  may already cover the successful lowering paths but miss target-register and
  diagnostic branches.
- LLVM codegen can reach 100% line coverage only by separating real helper
  behavior from invariant guards. Cover reachable paths with existing
  without-`llc` helper fixtures, but exclude only guards proven unreachable by
  LLVM opaque pointers, uniqued integer/float types, or `Type.is_array()`
  element guarantees.
- Refresh the real CPython build gate after backend coverage-only sweeps.
  Helper probes and single-object benchmarks can prove local branches quickly,
  but only the isolated `build/cpython-src-clean` `configure && make -j8` gate
  verifies CPython-wide configure, compile, link, freeze, and extension import
  behavior with the mypyc import tree.
- AArch64 global initializer helper coverage can close many branches quickly
  by combining a real sema fixture with narrowly scoped `_type_size`,
  `_member_align`, and `_eval_int_constant` stubs. Keep each stub active only
  for the exact negative probe so later pointer/lvalue checks still use real
  record layout and file-scope symbols.
- Direct AArch64 helper probes that exercise aggregate address or initializer
  paths must seed frame scratch state, not only TypeMap entries and slots.
  `_emit_local_array_initializer` and record-call address materialization use
  `_emit_scratch_*`, so set a realistic `_frame_size`/`_scratch_size` before
  probing those branches.
- Direct x86_64 address and initializer helper probes need both sema-visible
  declarations and explicit TypeMap entries for synthesized identifiers, calls,
  and compound literals. Register aggregate result slots by object id and
  restore any temporary `_emit_*` stubs immediately after the exact probe.
- Direct x86_64 `_emit_decl` helper probes need declaration slots keyed by the
  exact `DeclStmt` object id. Scope entries alone are insufficient because
  `_require_decl_slot` reads `_decl_slots[id(stmt)]`; register and clean up the
  synthetic slot around the probe.
- x86_64 array-initializer guard coverage must account for helper
  normalization. `_emit_array_initializer_to_address` calls
  `_complete_array_initializer_type` before validating length, so tests for
  impossible post-normalization lengths need a tightly scoped stub and an
  immediate restore.
- x86_64 helper coverage for register-sensitive branches should use a real
  frontend fixture for sema and record layout, then temporarily replace
  `_emit_expr` only around the exact helper under test. Restore the original
  method immediately so later probes do not inherit synthetic registers or
  types.
- Native backend coverage can advance quickly without replacing real CPython
  gates by separating helper contracts from executable source tests. For
  direct helper probes, seed the same backend state real lowering expects
  (`_func`, `_func_sym`, record definitions, and labels), then require a fresh
  full py311 coverage sample before moving the ratchet.
- x86_64 backend helper sweeps can cover guard-heavy branches cheaply by
  pairing a real frontend fixture with synthetic AST nodes. When mutating
  private backend state such as `file_scope`, `_func`, or parameter slots,
  restore or reset it before the next probe so the coverage test does not
  depend on leaked state.
- LLVM helper coverage needs line-level verification after each probe. LLVM
  can fold builder expressions into constants or canonicalize opaque pointer
  casts, so a passing assertion can still miss the intended branch; compare the
  coverage JSON before raising the ratchet.
- LLVM opaque pointers collapse many pointer-to-pointer casts to the same LLVM
  type. Before claiming a helper branch is covered, check the target coverage
  JSON: typed-pointer fallback branches may remain unreachable, and tests
  should document the current helper contract instead of forcing invalid
  preconditions for a coverage bump.
- Direct native backend helper tests need the same function state that real
  lowering would seed. Set `_func_sym`, build a realistic frame/parameter
  fixture, and then probe guard branches directly so the coverage gain stays
  fast without bypassing backend invariants.
- Switch and array-decay codegen helper coverage needs fresh LLVM insertion
  blocks after each terminator-producing probe. Reusing a terminated block can
  hide the branch under test or create invalid IR, while fresh blocks keep the
  helper sweep fast and deterministic.
- Codegen ratchet work should separate fast helper-edge sweeps from executable
  IR tests. Direct helper probes can close dozens of branch/line gaps quickly,
  but every ratchet move still needs a fresh full py311 sample because only the
  full parallel gate proves the project-wide denominator and remaining backend
  gaps.
- Before adding slower backend cases, close cheap utility-module branch gaps
  with targeted tests. A focused `cc_driver`/`host_includes` run can prove 100%
  line/branch coverage in under a second, then the full py311 gate can decide
  the ratchet.
- AArch64 TypeMap-recovery fallback coverage can stay fast by compiling a
  small real source fixture for sema symbols and record layouts, then removing
  only the synthetic `sizeof`/`alignof` AST nodes from the TypeMap. Cover both
  direct member and nested member chains, including pointer roots, before
  moving the ratchet.
- Parallel CPython `make -j8` turns per-process external tool probes into a
  reliability and speed problem. When the gate sets an explicit tool path such
  as `XCC_LLC`, trust that path and let the real invocation fail if it is wrong;
  keep expensive `--help` verification only for discovered `LLVM_CONFIG`/`PATH`
  candidates.
- Native global pointer initializer coverage should use valid source first for
  label/offset folding, such as extern symbols, static locals, compound
  literals, function designators, and commuted array offsets. Reserve direct
  helper probes for nonconstant rejection branches, and clear `TypeMap` entries
  for freshly constructed negative AST nodes that must behave as untyped.
- With branch coverage enabled, "100% for a module" means both missing lines
  and missing branches must be zero. Compact helper tests should cover
  executable branch alternatives first; reserve `no cover`/`no branch` for
  invariants such as fixed-output Keccak squeezing or duplicated guards that an
  earlier validation branch always rejects.
- Direct LLVM initializer helper tests can use GNU empty structs to reach
  runtime unbraced-aggregate fallback branches deterministically. Keep the
  fixture source valid, reset the builder back to the probe block after calling
  `_define_func`, and measure the full py311 gate before moving the ratchet.
- Direct AST helper tests that share a `TypeMap` should guard negative lookups
  against Python object id reuse. Before asserting unknown `typeof`,
  address-of, assignment-target, or other fallback behavior for a freshly
  constructed node, remove `id(node)` from the map so the test cannot
  accidentally inherit a type from an earlier temporary AST object.
- Native backend coverage should prefer public C source tests until the missing
  path depends on an internal register/slot choice that source cannot
  deterministically request. For those cases, instantiate the real backend
  generator and call the helper with typed AST nodes so the test still exercises
  real lowering code.
- Set coverage ratchets below the exact measured total, not at the rounded
  display value. Parallel full py311 samples can differ by a few covered lines;
  for example 93.92804600775712%-93.98956800855959% supports a 93.92% ratchet,
  while 93.99% would depend on the higher sample.
- LLVM helper coverage can safely target source-unreachable defensive branches
  when the fixture mirrors real builder state: create an insertion block, seed
  locals/type maps, and exercise ABI-sensitive helpers such as call coercion,
  casts, va intrinsics, and atomic promotion directly. Keep these tests fast,
  then verify both module missing-line reduction and a fresh full py311 gate
  before moving the ratchet.
- When sema already rejects invalid builtin calls, public-path tests should
  assert that frontend diagnostic separately if needed; backend duplicate arity
  guards need compact helper tests with synthetic AST calls, otherwise the test
  never reaches the branch it claims to cover.
- Coverage ratchets must be set from a strict gate sample, not the best recent
  JSON run. Parallel module coverage can shift a few lines in long backend
  files, so ratchet to the observed stable lower bound and record the exact
  gate evidence.
- When AArch64 and x86_64 share a native backend feature, a passing test on one
  target is not proof for the other. Tail flexible array members need explicit
  zero-initializer regression coverage per backend because x86_64 can otherwise
  fall through to ordinary aggregate zeroing and try to size `int[-1]`.
- Native backend constant-expression coverage should use frontend-reachable
  global/static initializer source instead of direct evaluator calls. One
  compact initializer matrix can cover many AArch64 and x86_64 evaluator
  branches while still proving emitted object data labels and keeping the
  parallel gate efficient.
- EVM helper tests for internal backend branches need enough synthetic frame,
  symbol, and local state to reach the intended guard. For function-pointer
  calls, a matching target signature is required before unsupported argument
  diagnostics run; for integer conversions, `char` follows the signed
  `SIGNEXTEND` path rather than an unsigned mask.
- For EVM initializer designator coverage, direct helper tests should exercise
  both memory and storage paths because they have separate diagnostics and slot
  arithmetic. Keep the cases table-driven, with exact messages, so defensive
  branches are covered without adding invalid C source fixtures.
- EVM constant-expression coverage needs to follow canonical project types:
  `char` is the signed 8-bit integer path, while `signed char` is not currently
  in the canonical integer map. Use small direct helper assertions to lock that
  behavior down instead of assuming C spelling aliases are normalized.
- EVM helper tests are valuable for backend-only defensive branches, but the
  helper fixture must initialize the same state that contract generation would
  initialize, such as `_functions_by_name`, before probing function-label or
  function-pointer paths. Keep these tests short and verify exact diagnostics so
  they complement, not replace, source-level EVM execution tests.
- Real CPython build validation needs a clean source tree, not just a clean git
  status. If the default checkout has ignored build artifacts, use a clean git
  worktree under ignored `build/` for `cpython-build`; do not clean the user's
  CPython checkout just to make the gate pass.
- Direct LLVM helper tests are efficient for defensive and constant-expression
  fallback paths, but assertions must follow traced helper semantics. For
  example, `_infer_array_init_length` with nonconstant designators falls back to
  sequential length `1`, not the syntactic high designator.
- Some LLVM backend defensive branches are intentionally unreachable from valid
  source after sema validation. Cover those with direct helper tests instead of
  adding invalid C fixtures or slow link/run cases; keep the helper tests small
  and measure missing-line reduction before raising the ratchet.
- Coverage additions should be measured at the target module before keeping
  them. A plausible x86_64 aggregate-expression test did not reduce missing
  lines because returns used address-based aggregate initialization instead of
  `_emit_subscript`/`_emit_member`; removing no-gain tests keeps the parallel
  gate efficient while the ratchet moves from measured coverage only.
- Unnamed bit-fields do not participate in record initialization. Native
  backend initializer mapping must skip them before assigning positional
  initializers, while record access/layout code still sees them for padding and
  alignment. Cover both designators and positional compound literals when a
  bit-field ABI test includes zero-width separators.
- Switch `case` constants and array designator indexes use separate codegen
  evaluators, so coverage for one does not prove the other. When extending
  integer constant-expression support, exercise both public paths. Union
  first-member aggregate initializer shapes may still be rejected in sema, so
  keep LLVM aggregate coverage focused on frontend-reachable record and array
  cases unless sema is being changed too.
- EVM builtin arity diagnostics are sema-owned for source-level tests because
  builtin signatures are registered before backend lowering; backend arity
  checks are defensive and should not drive coverage tests. Also, `_Alignof`
  accepts some type names such as pointer/scalar forms but rejects array
  type-names in sema, so EVM constant-expression coverage should probe the
  supported frontend paths instead of forcing backend-only branches.
- For backend coverage, prefer frontend-reachable behavior. EVM `break` and
  `continue` outside loops are rejected by sema before the backend, so
  backend-only error lines should not drive invalid C tests. EVM array compound
  literals need explicit bounds like `(uint256[2]){...}`; incomplete forms
  remain diagnostic.
- Tests for function-scope `__func__` must compile in strict C mode. The
  default GNU compatibility path defines `__func__`/`__PRETTY_FUNCTION__` as
  preprocessor compatibility macros, so a native backend test that wants the
  semantic function-name object should pass `FrontendOptions(std="c11", ...)`.
- Coverage progress should keep mixing executable semantic tests with cheap
  target-text probes. LLVM global range designators and EVM initcode storage
  initializers need real execution because they prove constant initialization
  behavior, while x86_64/AArch64 builtin variants are efficient assembly
  assertions for host-independent lowering branches. When adding AArch64 text
  assertions, match stable opcode/label prefixes instead of generated numeric
  suffixes.
- LLVM local declaration initialization must route aggregate targets through
  initializer-to-address lowering even when the initializer is not braced.
  Sema can type scalar aggregate initializers as the destination aggregate, so
  a same-type direct store is only safe for a real whole-aggregate value. For C
  scalar aggregate initialization, zero the destination first and then
  initialize the first member so omitted members keep C's zero-initialization
  semantics. Real CPython validation should run against a clean source
  worktree; dirty source checkouts and single-object substitutes are not
  acceptable evidence for the project gate.
- Aggregate call-result member access needs both executable LLVM coverage and
  target-specific native text coverage. Small register-return records and
  large indirect records take different storage paths; x86_64 assertions should
  prove the call result is materialized before member offsets are applied,
  while the LLVM test should still link and execute the same semantic shape.
  Pointer-difference scaling and unordered floating branches are cheap adjacent
  native checks that raise coverage without replacing real execution tests.
- Backend coverage should include small text-level native tests for target-only
  lowering branches that cannot execute on every host. x86_64 floating
  logical-not, 32-bit `cdq` division, and bit-field postfix old-result
  preservation are cheap assembly assertions; pair them with executable LLVM
  tests when the same source shape has semantic risk, such as string
  initialization of `char[]` record members.
- Backend coverage probes should distinguish unreachable fallback branches from
  public compiler behavior. The EVM unnamed-parameter backend diagnostic is
  parser-blocked, so it is not a useful test target; better targets are
  executable global initializers, native slot-collection shapes, and LLVM
  layout cases such as alignment-driven union tail padding.
- LLVM codegen coverage should bundle small control-flow and declaration-edge
  programs only when they execute through `llc` and the platform linker. One
  compact executable source can cover block-scope `extern` scalar/array reads,
  void expression returns, nested scalar brace initialization, forward `goto`,
  endless `for` with `break`, and alloca insertion after a terminated block
  without weakening the real compiler path.
- Inline-function coverage should check both absence and forced local
  emission. A fast assembly test can prove unused inline bodies stay out of
  native output while referenced inline designators are emitted as non-global
  local functions. For ABI coverage, text-level x86_64 tests can cheaply reach
  SysV stack-passed aggregate chunks that are skipped by native execution on
  non-Linux hosts.
- Host-skipped native execution paths still need public compiler coverage.
  Text-level x86_64 assembly tests are effective for sparse designators,
  local incomplete array storage, and nested `offsetof` constants, while
  AArch64 should keep corresponding `sizeof` and member-chain cases executable
  when the Darwin runner can link and run the generated assembly.
- Native backend coverage should include text-level tests for branches that
  are otherwise hidden behind host-specific execution skips. On non-Linux
  hosts, x86_64 bit-field compound assignment and update execution tests do
  not run, so small assembly assertions are needed to keep mask/load/store
  lowering covered. For AArch64, one executable compound-literal test can cover
  both scalar array members and arrays of record members without adding another
  slow module.
- Grouped declaration coverage is high leverage across backends. One small
  source with grouped file-scope globals and grouped static locals exercises
  collection, symbol naming, and data emission in both x86_64 and AArch64
  without adding slow execution work; pair those text checks with executable
  LLVM tests for semantic behavior such as comma expressions, string literal
  caching, wide string expressions, and explicit `return;`.
- LLVM codegen coverage should favor small executable programs that hit real
  fallback lowering, such as implicit zero returns and grouped file-scope
  declaration emission. Probe call-coercion branches before testing them:
  several are intentionally blocked or normalized by sema and explicit casts
  before `_coerce_call_args`, so source-level tests cannot naturally reach them.
- EVM backend diagnostic coverage should start with a source-level reachability
  probe. Builtin arity mistakes are sema-owned and do not reach EVM codegen,
  while ABI shape checks, unsupported internal parameter types, return-array
  arity, function-pointer target validation, unsupported local object types,
  and aggregate locals with scalar initializers are reachable through ordinary
  `compile_source` plus `generate_evm_bytecode`.
- EVM initializer coverage is more efficient when nested designators are folded
  into existing local bytecode and storage initcode tests. A single source can
  exercise recursive designator descent through arrays of records in both
  memory and persistent storage without adding another slow module-level test.
- AArch64 backend coverage can stay executable while still reaching data-layout
  and ABI branches. Global pointer initializers are cheap run tests for compound
  literals, string/null pointers, array decay, pointer arithmetic, and subobject
  addresses; record-return tests should cover both small register returns and
  large indirect returns in one linked program. For Darwin aggregate varargs,
  small records are copied inline from the current `va_list` stack pointer while
  larger records are passed by reference, and XCC-owned variadic callees need
  execution tests just like XCC-owned callers.
- Dense LLVM coverage tests should still execute real C behavior. One small
  source program can cover local enum lookup, function-pointer dereference,
  pointer updates, pointer differences, mixed float comparisons, and compound
  floating assignment while proving the generated IR links and returns the
  expected status.
- Wide string array initializers need element-count and element-width handling,
  not byte-count handling. `u""` maps to 16-bit elements, while `U""` and `L""`
  map to 32-bit elements; using the ordinary string literal pointer path can
  produce invalid LLVM pointer-to-array bitcasts for local arrays.
- AArch64 atomic coverage is most efficient as executable clusters that verify
  both the generated inline lowering and runtime value transitions. Generic
  `__atomic_*` forms, lock-free probes, fences, old-value/new-value RMW
  variants, and `__sync_*compare_and_swap` share the same lowering machinery,
  so one small run test can cover many branches without introducing a slow
  object-file-only benchmark.
- EVM coverage work needs a reachability probe before adding tests. Builtin
  arity mistakes are sema-owned diagnostics, so codegen arity fallbacks are not
  useful source-level coverage targets; grouped declarations, storage
  initializer initcode, pointer/member lowering, and backend-only diagnostics
  produce better coverage without bypassing the public compiler path.
- LLVM intrinsic signatures are stricter than C builtin call syntax. For
  `__builtin_memset`, the C fill argument is an `int`, but LLVM's memset
  intrinsic requires an `i8`; always coerce builtin operands to intrinsic
  parameter types before building the call. Floating classification builtins
  have the opposite trap: the result is `int`, but non-floating arguments must
  be converted to a floating operand type before emitting `fcmp`.
- Test entrypoints drift unless tox, CI, pre-commit, and README all name the
  same commands. Keep one parallel coverage runner as the default test path,
  and keep full CPython build validation as a separate real-project gate from
  frontend file benchmarks. Ratchet actual coverage upward from measured
  reality; do not claim 100% coverage until the report proves it. Keep the
  CPython gate mypyc-accelerated so real-project validation stays useful during
  normal iteration.
- Parallel coverage must isolate data per run. `coverage erase` does not remove
  arbitrary stale `.coverage.*` files, while `coverage combine` scans the data
  directory by default; use a per-run `COVERAGE_FILE` so ratchets are based on
  the current worker set only.
- Unbraced aggregate initializers need one shared consumption model across sema
  and codegen. Distinguish complete aggregate initializers, such as char-array
  strings and same-type aggregate expressions, from flattened subobject items;
  otherwise arrays of records and multidimensional arrays either reject valid C
  or store values in the wrong subobject.
- `sizeof` and `_Alignof` can share parsing and type-resolution paths, but the
  backend constant lowering must branch on the expression kind. Record alignment
  also has to use member storage alignment, including `_Alignas`, not just the
  member's base type alignment.
- Record layout helpers must use a single member-storage-alignment path across
  record alignment, size calculation, member access, ABI classification, and
  global initializer padding. Fixing only `__alignof__` leaves `sizeof` and
  offsets vulnerable to the same `_Alignas` drift in other backends.
- Case-label constant folding is executable control flow, not just parser
  bookkeeping. Unsupported integer operators silently collapse to zero in the
  backend and redirect `switch` dispatch, so logical and comparison operators
  need source-level execution regressions just like arithmetic case labels.
- LLVM constant arrays can be `ConstantDataArray` values with zero operands.
  Constant-initializer byte extraction must use aggregate-element lookup before
  falling back to null elements, or union members initialized through byte
  arrays silently become zero in global storage.
- Coverage debt should be paid with focused, cheap unit tests before leaning on
  CPython builds. A real-project build proves integration, but it does not
  replace branch tests for parser, preprocessor, host-discovery, and semantic
  helper edges.
- Coverage-directed tests should prefer real source-level behavior when it is
  reachable, but direct helper tests are acceptable for defensive fallbacks
  that production syntax cannot naturally trigger. Keep those tests narrow and
  paired with full tox gates so coverage work does not mask integration risk.
- Coverage ratchets should move only after a fresh full-gate coverage run, and
  the config contract test should pin the exact new threshold. Record the exact
  JSON total and missing-line count separately from the rounded report column.
- Backend coverage should not chase branches that production source cannot
  reach because sema owns the diagnostic first. EVM builtin arity errors are
  mostly rejected before codegen, so spend backend tests on executable lowering
  behavior unless a backend-only fallback is genuinely reachable.
- Moving the total coverage ratchet requires backend coverage work, not only
  parser/preprocessor polishing. Keep making cheap helper modules 100%, but
  plan larger backend test slices separately so the global number can approach
  100% without making every edit wait on CPython builds.
- Do not assume backend label syntax carries across targets. x86_64 uses
  dotted `.L.<function>.*` labels while AArch64 currently emits `L_<kind>_*`
  labels and underscored globals, so coverage assertions should follow the
  target's actual ABI and assembly style.
- Partial object-file smoke tests are useful for fast localization, but they
  are not integration evidence. A full clean CPython `configure && make -j1`
  later exposed `_ssl.c` and `_testcapimodule.c` failures that three selected
  files missed. Treat per-file rebuilds as debugging aids and require a fresh
  build directory for the final CPython claim.
- CPython out-of-tree builds require source cleanliness beyond `git status`;
  ignored build artifacts can trip `check-clean-src`. Use an isolated clean
  worktree for real CPython build gates instead of cleaning the user's primary
  CPython checkout.
- Compiler-compatibility bugs often hide in macro-expanded system-header
  shapes, not in the visible source line. OpenSSL's `SSL_ctrl` macros pass
  `const char **` through `void *`, and CPython's tests use GNU
  `__extension__ __alignof__(expr)` under C11. Minimize these cases and compare
  against real GCC and Clang before deciding whether XCC is too strict.
- A passing CPython build is not a substitute for the full compiler test suite.
  The build can miss dialect edges such as GNU `return int_expr;` in a `void`
  function, where the expression's side effects must still be emitted while
  strict C11 continues to reject the same source.
- Performance comparisons against GCC/Clang need a representative XCC runtime.
  Pure-Python XCC is useful for diagnosis, but published frontend-throughput
  comparisons should use the mypyc-precompiled import tree and record whether
  compiled artifacts were rebuilt or reused.
- Performance changes need a profile -> optimize -> re-profile loop on real
  translation units. Parser micro-optimizations that pass unit tests can still
  fail to improve CPython-scale throughput; keep only changes that move the
  measured hotspot.
- The preprocessor's token-rendered spacing is observable behavior in tests.
  Skipping tokenization for speed is safe only when the shortcut cannot change
  output formatting, such as lines without identifiers.
- CPython frontend benchmarks have a large cold-start component from host
  include discovery, header traversal, and macro state. Report cold and warm
  measurements separately instead of mixing subprocess and in-process timings.
- Keep diagnostics deterministic and covered by negative tests.
- Compiler validation should pair differential execution tests with negative
  boundary tests; matching `clang` on valid programs is not enough if the
  driver/frontend also accepts inputs outside XCC's explicit contract.
- Do not hard-code host paths, dates, or toolchain assumptions.
- Compare against permissively licensed Clang fixtures.
- Treat ABI/layout bugs as high severity.
- Add a reproducer before changing behavior.
- Ethereum ABI selectors use pre-FIPS Keccak-256, not `hashlib.sha3_256`.
  Keep a known selector regression test when adding EVM ABI behavior.
- EVM arithmetic tests need execution checks, not just opcode snapshots. Stack
  order bugs in non-commutative operators such as `-` and `-=` can still emit
  plausible bytecode while returning 256-bit wrapped wrong answers.
- EVM file-scope storage variables need deterministic slot assignment tests.
  Nonzero initial storage is deploy-time initcode behavior, not runtime
  bytecode behavior, so reject it until the target grows an initcode path.
- EVM pointer tests need execution through bytecode. Pointer arithmetic must
  scale by the backend memory slot size, and ABI dynamic arrays need a concrete
  calldata copy test so selectors, offsets, and memory reads stay aligned.
- EVM dynamic ABI array tests need non-`uint256` element types. A `uint256[]`
  copy can pass while `uint32[]`, signed, or boolean arrays still fail to apply
  the same element conversions used for scalar ABI parameters.
- EVM bit-field tests need to inspect the stored word, not only the loaded
  member value. A masked load can hide initcode or store paths that wrote an
  untruncated value into memory or storage.
- EVM unnamed bit-field support needs positional initializer tests. A layout
  change can allow the record allocation while `{...}` still tries to
  initialize the padding field instead of skipping to the next named member.
- EVM expression-order tests need side effects, not only returned constants.
  Logical and conditional lowering must prove skipped branches do not write
  storage before treating it as C-compatible control expression support.
- EVM signed integer tests need ABI two's-complement inputs and signed result
  decoding. Unsigned opcodes can pass positive-only tests while breaking C
  `int` comparison, division, modulo, and arithmetic right shift.
- EVM integer conversion tests need both narrow and expression-boundary cases.
  A cast-only test can miss 256-bit word values leaking through local stores,
  returns, and unsigned arithmetic wraparound comparisons.
- EVM internal-call tests need caller locals that are used after the call.
  A helper can appear to work while sharing `_LOCAL_BASE` storage with its
  caller and corrupting live local values.
- EVM `sizeof` tests need side-effect operands. A constant result alone does
  not prove the backend avoided evaluating expressions such as
  `sizeof(marker = 99)`.
- EVM `switch` tests need separate inputs for break, fallthrough, direct case
  entry, and default. A single matched case does not prove the switch end label
  or label-to-label fallthrough is correct.
- EVM character literal tests need both runtime returns and `case` labels, with
  ordinary, common escaped, hexadecimal, and octal forms. The runtime expression
  path and integer-constant path can fail independently.
- EVM `offsetof` tests should include nested members and assert byte offsets,
  not slot offsets. The backend stores aggregate layout internally in 32-byte
  words, but C `__builtin_offsetof` reports bytes.
- EVM `_Generic` tests need a side-effecting control expression. Selecting the
  right association is not enough; the control expression must be type-checked
  but not emitted or executed.
- EVM statement-expression tests should include a local declaration, an
  intermediate side effect, and a final expression-statement result. Emitting
  the whole compound statement through the normal statement path would pop the
  value that the enclosing expression needs.
- EVM user labels must be unique per emitted function copy, not just per source
  function. The ABI dispatcher body and internal helper body both lower the
  same C labels; duplicate assembler labels can make an ABI `goto` jump into an
  internal-return body.
- EVM labels-as-values should reuse the same function-copy-local label naming
  as direct `goto`. `&&label` stores an EVM byte offset, so mixing ABI and
  internal body labels would make later indirect `JUMP` targets mode-crossing.
- EVM compound literals need planned frame slots, not opportunistic allocation
  while emitting code. Dynamic ABI array memory starts after planned frames, so
  late compound-literal allocation can collide with calldata copies.
- EVM string literals follow the target word-object layout, not byte-packed C
  memory. Tests should assert subscript behavior through char-word slots and
  include the null terminator so pointer-expression storage is proved.
- EVM record initializers need omitted-member checks. A full initializer can
  pass while uninitialized frame words leak through `{7}`-style partial record
  initialization.
- EVM aggregate assignment tests should cover memory-to-memory,
  memory-to-storage, and storage-to-memory copies. A local-only copy can miss
  the different address units: memory uses byte offsets while storage uses word
  slots.
- EVM anonymous record member support needs both access and initializer tests.
  Recursive promoted-member lookup can pass assignment syntax while positional
  initializers still reject the anonymous owner field.
- EVM aggregate initcode tests should assert individual storage slots as well
  as runtime reads. A flattened initializer can return the right aggregate sum
  while still writing the wrong declaration-order slot.
- EVM designated initializer tests should cover both local memory reads and
  initcode storage slot assertions. Field/index designators use different
  address units across memory byte offsets and storage word slots.
- EVM no-op syntax still needs backend coverage. Empty statements, block
  typedefs, and checked `_Static_assert` declarations should emit no bytecode,
  but an unsupported-statement fallback can reject otherwise valid C bodies.
- EVM storage string literal tests should assert individual slots. The runtime
  read can hide mistakes in escape decoding, null terminator padding, or the
  initcode flattening order for char-word arrays.
- EVM static local tests need repeated runtime calls against the same storage
  dict. A single call cannot distinguish persistent storage from a local frame
  that is reinitialized on every entry.
- EVM enum support needs both runtime expression and integer-constant tests.
  `case ENUM_VALUE` exercises a different path than `return ENUM_VALUE`.
- EVM pointer arithmetic tests should include pointer-pointer subtraction, not
  only pointer-plus-integer. Otherwise the backend can accidentally scale a
  pointer address as though it were an integer index.
- EVM ADDMOD/MULMOD tests need operands that distinguish native arbitrary-width
  modular arithmetic from a wrapped 256-bit C expression followed by `%`.
  Otherwise a lowering bug can still produce small correct-looking results.
- EVM MSTORE8 tests need byte addresses, not word-scaled pointer arithmetic.
  Cast through `__evm_uint256` or target a base pointer directly when proving
  single-byte writes and `MSIZE` behavior.
- EVM PC tests should avoid fixed byte-offset expectations. Assert a stable
  relation such as nonzero execution position because dispatcher and preceding
  lowering changes legitimately move the opcode.
- EVM MCOPY tests should copy visible high-order bytes from a word value and
  inspect transient storage separately. A return value alone can hide whether
  `TSTORE` persisted in the transaction-local map.
- EVM PUSH0 changes byte offsets for later labels. Prefer execution checks and
  mnemonic/byte presence over exact dispatcher offsets unless the test is
  explicitly about label address calculation.
- EVM raw RETURN tests should put a distinct C `return` after the builtin.
  That proves the terminal opcode wins and the normal ABI return path is not
  accidentally reached.
- EVM raw LOG and REVERT memory-range tests should slice across word
  boundaries. That catches swapped pointer/length operands and proves byte
  offsets are honored instead of only word-aligned data.
- EVM deploy/initcode support needs driver-level coverage, not just a Python
  API test. Use an initialized storage global so runtime `.bin` cannot mask
  whether the CLI actually selected creation bytecode.
- EVM ABI decoder tests should include truncated calldata, not only valid ABI
  payloads. `CALLDATALOAD` returns zero past the end, so missing bounds checks
  can look like valid zero arguments.
- EVM dynamic ABI offset tests need malformed offsets that are still in bounds.
  Offset-zero and misaligned-offset payloads can decode as empty arrays unless
  the backend checks the ABI head boundary and 32-byte alignment explicitly.
- EVM LOG builtin tests should verify topic order for multi-topic logs. A
  single-topic test cannot catch reversed stack emission for `LOG2` through
  `LOG4`.
- EVM Keccak/SHA3 tests should hash real memory bytes, not just assert an
  opcode appears. Word-object memory layout makes the exact byte range part of
  the contract.
- EVM environment opcode tests should combine runtime values with distinct
  weights and assert assembly mnemonics. That catches both wrong opcode
  selection and MiniEVM field wiring.
- EVM account-query tests should use explicit fixture maps for balances,
  code sizes, code hashes, and block hashes. Unknown values should default to
  zero, matching the EVM's query-style behavior in tests.
- EVM raw calldata tests should include bytes beyond the ABI-decoded head.
  That proves `CALLDATALOAD` and `CALLDATACOPY` operate on raw calldata, not
  just values already copied into local frame slots.
- EVM codecopy tests should compute expectations from the emitted bytecode.
  Runtime length and first-byte values can shift as the dispatcher changes, so
  hard-coded code bytes make the test brittle.
- EVM extcodecopy tests should use an address-keyed code fixture with nonzero
  copy offsets. That catches both wrong stack argument order and accidental
  copying from the current contract's runtime code.
- EVM return-data tests should preload nonempty return bytes and copy a
  nonzero offset. That proves `RETURNDATACOPY` reads prior-call return data,
  not calldata or deployed code memory.
- EVM CREATE tests should build initcode bytes at the start of an EVM word.
  Local `uint256` stores are big-endian 32-byte memory writes, so short bytecode
  constants need shifting before `CREATE` copies from offset zero.
- EVM CREATE2 tests should assert the salt separately from initcode bytes.
  `CREATE2` shares the `CREATE` memory boundary, so salt coverage is what keeps
  deterministic creation stack order from silently regressing.
- EVM SELFDESTRUCT tests should prove halting, not just opcode emission. A
  void builtin can otherwise leave normal function-return code reachable after
  the terminal opcode.
- EVM CALL tests should assert both sides of the memory boundary. Checking only
  the success flag can miss wrong stack argument order; record gas/address/value
  and input bytes, then assert returned bytes land in the requested output
  buffer.
- EVM CALLCODE tests should keep an explicit value argument even though the
  call executes in the current context. It shares the memory boundary and stack
  arity with `CALL`, but must still prove the legacy opcode is emitted.
- EVM STATICCALL tests should keep the call trace value at zero. It shares the
  memory boundary shape with `CALL`, but its stack omits the value argument.
- EVM DELEGATECALL tests should preload a nonzero current call value. That
  catches accidentally lowering it like `CALL` with a stack value argument or
  like `STATICCALL` with an always-zero value.
- Keep benchmark matrices explicit: pure interpreter environments should measure
  the source tree under that interpreter, while compiled Cython/mypyc variants
  should pin to the CPython version used to build compatible extension modules.
- Mypyc enforces dataclass field annotations at runtime. If a parser recovery
  path intentionally accepts synthetic enum token kinds, annotate the token
  field to that public contract rather than the common concrete enum.
- For pure-Python Cython performance experiments, disable Cython function
  binding semantics unless the benchmark needs Python descriptor/signature
  fidelity; default binding overhead can hide the real throughput win.
- Wide string literal labels need the same alignment as their element type.
  Correct UTF-32 bytes are still unsafe if `L"..."` follows a byte string at an
  odd address; optimized libc routines may assume `wchar_t *` alignment.
- `_Bool` is not an integer truncation. When lowering scalar values to C bool,
  compare against zero and write 0/1; large bit flags often have a zero low
  byte.
- Direct-call selection must run after local shadowing checks. A block-local
  function pointer can legally have the same name as a file-scope function, and
  calls through that identifier must use the local slot instead of the global
  function signature.
- Storage initializer constant folding must preserve non-integer word values.
  Function pointer labels need branch selection before generic integer constant
  evaluation, or constant conditionals discard the selected runtime label.
- EVM local declaration planning must classify block-scope function prototypes
  before allocating locals. They are declarations only, not stack/memory
  objects, and direct helper-call lowering should remain available.
- EVM function pointer return tests should keep the selector helper internal
  and immediately indirect-call the returned value. That proves runtime labels
  survive the return slot without making function pointers part of the public
  ABI parameter surface.
- EVM word pointer return support needs two tests: one static helper returning
  a memory pointer that is dereferenced by the caller, and one exported
  function that still rejects pointer returns at the ABI boundary.
- EVM internal helper parameter validation should be separate from exported ABI
  parameter validation. Function pointer parameters are valid word values for
  static helpers but must not become public ABI parameter types.
- EVM internal aggregate parameter tests should mutate the caller's record
  after the call. That proves direct helper arguments are copied into the
  callee frame by value instead of aliasing caller storage.
- Conditional expression codegen has to apply the expression's final type to
  each branch, not just trust branch-local expression widths. Otherwise an
  `int -1` branch in a `long` conditional returns `0xffffffff` and breaks
  CPython runtime logic such as Unicode substring search.
- Block-scope function prototypes are still function declarations, not local
  storage. Sema must register them as callable signatures or direct-call codegen
  will fall back to identifier lookup and lose extern functions declared inside
  a CPython test helper body.
- Compound literals are lvalues with storage, even when they appear where the
  backend wants a scalar expression. Arrays and aggregates must be initialized
  into a temporary and decay to that address for call arguments.
- Compiler pseudo-identifiers can surface through system or project macros, not
  only direct source spelling. When the project already approximates
  `__func__` as a string macro, related GNU spellings such as
  `__PRETTY_FUNCTION__` need the same predefined compatibility surface.
- Target asm policy is target-specific. x64 Linux CPython headers can expand
  ordinary macros such as `__cpuid_count` into primary-file GNU asm, so the
  native x64 target must strip those statements before parsing even if another
  native target keeps a stricter rejection policy.
- Parallelize long frontend trial sweeps per translation unit, but keep reports ordered.
- When a build threatens memory, split frontend, IR generation, and `llc`
  under RSS monitoring before running `make`.
- Keep codegen's type canonicalization in lockstep with sema; a single
  `bool` vs `_Bool` mismatch can make anonymous record matching fall back to
  the default scalar size.
- Constant initializer evaluation must search function-local static globals
  before file-scope symbols, because nested CPython slot arrays refer to
  earlier local static arrays by identifier.
- Do not infer incomplete array length from initializer item count; sparse
  designators and ranges make the bound the largest initialized index plus one.
- Multi-line macro collection must operate on preprocessing structure, not just
  apparent physical lines; block comments and inactive conditional branches can
  appear inside macro arguments.
- Native codegen cannot treat inline-use discovery as direct-call-only. Inline
  functions can be required by function-pointer tables, conditional designators,
  or `extern inline` bodies even when no call expression names them directly.
- When a backend emits an inline body because it did not inline the call, emit
  it with translation-unit-local linkage. Header inline helpers commonly appear
  in many objects and must not become duplicate external definitions.
- Compiler builtins are not library calls. If the frontend accepts a
  `__builtin_*` name, each target backend needs either a real lowering or an
  early diagnostic; otherwise whole-program builds fail late at link time.
- On Darwin AArch64, imported data symbols are not ordinary page-addressable
  labels. Load their address through GOT relocations first, then load/store the
  variable value through that address.
- Direct calls and function designator addresses need different Mach-O
  relocations for external functions: `bl _name` is fine for calls, but taking
  an imported function's address must load it through the GOT.
- Function-call argument evaluation needs an ABI save plan, not just
  left-to-right emission. Any later argument or indirect callee that performs a
  nested call can overwrite x0-x7 or d0-d7 values already prepared for the
  outer call.
- Binary-expression lowering needs the same preservation discipline. A left
  operand kept only in a caller-scratch temp register can be overwritten by
  recursive RHS arithmetic or calls before the final compare/operator uses it.
- Compound assignment is a binary operation after the lvalue load. For local
  scalars, spill the old value across RHS lowering before applying `+=`,
  `*=`, shifts, or bitwise operators.
- Do not keep a local array element destination address live in x11 while
  evaluating a scalar initializer. Address calculation is cheap and
  side-effect-free; recompute it after the value is ready.
- Do not assume stack slots fit AArch64's immediate load/store operands. Large
  CPython frames can place scratch/spill slots past the direct SP-offset range;
  materialize the address in a scratch GPR first.
- Update expressions can be nested inside address formation. If the requested
  result register is also the usual lvalue-address scratch, pick a different
  address register for the load-modify-store.
- Large-offset stack helper code has its own scratch-register effects. When an
  aggregate source address is live in x12, reload saved destination addresses
  with a materialization scratch that cannot overwrite x12.
- Argument-preservation helpers must not make untracked dynamic `sp` changes
  before recursively lowering nested call arguments; local slot offsets are
  frame-relative only under the planned stack layout.
- When a call result occupying x0/x1 or d0/d1 becomes a later argument, move
  overlapping return registers high-to-low so x0→x1 does not overwrite the
  source for x1→x2.
- Pointer subscript scaling has three live roles: base, index, and scale. For
  non-power-of-two element sizes, choose a scale scratch distinct from both
  base and index before multiplying.
- In nested subscript lowering, an outer index register stays live while the
  base expression is recursively lowered. Allocate index scratch registers by
  nesting depth instead of reusing one fixed register for every level.
- Nested subscript scale materialization must also respect the live-index set;
  otherwise a non-power-of-two inner row size can overwrite the outer column
  index after the index-register allocation itself has been fixed.
- String literal prefix matters in native data emission. `L""`, `u""`, and
  `U""` are not byte cstrings; pointer initializers must reference storage
  encoded at the literal's target code-unit width.
- Real-build compiler wrappers must preserve the caller's working directory.
  For relative compile inputs, prefer a `PYTHONPATH=... python -c ...` wrapper
  over `uv --directory ... run xcc`, which changes cwd and makes
  project-relative source paths disappear.
- Target OS is part of preprocessing state, not just codegen state. A Linux
  native target must not inherit Darwin `__APPLE__`/`__MACH__` macros while
  compiling the same frontend on a Mac host.
- A no-LLVM Linux target needs driver tests that reject accidental `llc` and
  clang invocations; using generated assembly plus gpu02 `cc` keeps the first
  smoke gate honest.
- System headers use GNU spelling variants in ordinary declarations, not only
  in exotic corners. Treat `__restrict`/`__restrict__`, `__extension__`, and
  compiler version macros as part of the target contract before blaming glibc.
- Autoconf probes often fail closed: a compile/codegen error can be recorded
  as a libc bug such as broken `getaddrinfo`. Always inspect `config.log`
  before accepting the human-readable configure diagnosis.
- SysV floating codegen must stay in XMM registers for the full load/compute/
  store cycle. Integer fallback in a single compound-assignment edge can
  surface much later as an assembler error inside a runtime feature probe.
- File-scope enum constants from headers are ordinary integer constants at
  codegen time. If a backend only checks function-local enum bindings, Linux
  socket and address-family probes will lower `SOCK_STREAM`-style names as
  unresolved variables.
- SysV aggregate calls are not an optional late feature once CPython object
  compilation starts. Even parser code passes `Py_complex` by value, so small
  records need chunk classification and parameter spill paths before broad
  `make` progress is meaningful.
- CPython object headers rely on GNU anonymous struct/union member promotion.
  Parsing the anonymous fields is not enough; every native backend member
  address path must recursively find promoted fields such as `ob_refcnt`.
- Variadic support can surface from inline headers before compiling obvious
  formatting implementations. For x86_64 SysV, even a first-stage va_list
  lowering should be explicit about whether it handles stack-only variadics or
  the full register save area.
- CPython includes expose bit-fields in hot headers such as Unicode state and
  interpreter/thread state structs. Native backends need read-modify-write
  bit-field lowering early; writing the whole declared integer type corrupts
  neighboring flags.
- Tagged enums can escape the semantic resolver as `enum` object or parameter
  types in generated CPython AST helpers. Each native ABI layer should size
  them like `int` even when enum constants themselves already lower correctly.
- Generated parser tables use file-scope compound literals as anonymous
  storage. A native backend needs a data-section path for those literals before
  `Parser/parser.c` can compile.
- Lexer state setup uses compound literal assignment into an array element.
  Record assignment support should include both copy-by-size and direct
  designated-member initialization, not just scalar member stores.
- CPython's abstract/object headers use small struct returns for iterator send
  pairs and adaptive backoff counters. The x86_64 backend needs return-register
  classification as soon as object files start compiling, not only call
  argument classification.
- Local record initializer lists show up in ordinary object code (`Py_buffer`
  temporaries), not just generated parser data. Reuse the same in-place record
  initializer used for compound literal assignment.
- x86_64 has direct signed integer-to-float instructions, but unsigned 64-bit
  conversion needs a high-bit path. CPython bytearray sizing code reaches this
  through `size_t` arithmetic.
- `va_start` without `va_arg` only gets through parser headers. `bytesobject.c`
  needs the read-and-advance side of variadic lowering immediately afterward.
- Sizing enum objects is not enough; expression conversion paths must also see
  bare enum values as `int`, or pointer arithmetic can still fail after local
  loads succeed.
- Array-to-pointer decay is needed in binary pointer arithmetic, not just call
  arguments and identifier loads. Generated formatting code can form
  `char[N] + int` directly.
- Python `int(lexeme, 0)` is not a C integer parser: C legacy octal literals
  like `0377` need explicit base-8 handling.
- Array decay must be applied per expression form. Fixing calls and binary
  pointer arithmetic still leaves `*array` broken unless unary dereference
  handles it explicitly.
- Casts are another array-decay entry point. A string literal cast to `char *`
  should keep the address value, not enter scalar conversion for `char[N]`.
- A small aggregate call result is not addressable. Assignment must consume the
  return registers directly and store them to the destination lvalue.
- Comma expressions can still be lvalues through their right operand in GNU C
  macro-shaped code. Address formation needs to preserve the left side effect
  and then continue through the normal right-operand address path.
- `{0}` inside a record compound initializer may target an aggregate member.
  Since the destination record is already zeroed, that member needs no scalar
  store; treating the aggregate as one integer creates invalid wide moves.
- Designated initializer members can copy whole nested records, as in
  `.locals = locals`. Reuse the aggregate assignment copy path for these
  members rather than scalarizing the member type.
- SysV aggregate returns split sharply at 16 bytes. Larger records are not a
  "more chunks" case; they consume a hidden first integer argument pointing at
  caller-owned storage and shift the visible integer parameters.
- CPython's math-heavy object code can expose GNU builtins that are never real
  link symbols, such as `__builtin_isinf_sign`. Accepting the builtin in sema
  is only half the fix; native targets must lower it directly.
- A call returning a small aggregate can immediately feed another aggregate
  parameter. That value has no address; the outer call must consume the inner
  call's return registers once, in chunk order.
- Local aggregate initialization has the same call-result problem as aggregate
  assignment. `struct S s = make();` needs to store return chunks into `s`, not
  pass through scalar `_store_value_to_slot`.
- Expression result metadata matters for floating values. If a branch lowered
  into `xmm0`, the returned `_Value` must say `xmm0`; otherwise later stores
  can emit invalid integer-register `movsd`.
- Address computation and value loading have separate register classes. A
  floating dereference still needs the pointer in a GPR before loading the
  pointee into an XMM register.
- Floating contexts can request an XMM target for a child expression that is
  still integer or pointer typed. Each scalar lowering path must re-check the
  expression type and choose the matching register class locally.
- GNU inline asm can appear in the middle of a macro-expanded statement, not
  only as a whole physical source line. Strip it as a balanced statement
  segment or system-header macros can leave parser-visible asm operands behind.
- `__attribute__((__transparent_union__))` is a call-compatibility rule, not a
  harmless typedef decoration. Glibc socket prototypes rely on member pointer
  arguments being accepted while normal union assignments stay strict.
- Function-like macro invocation can cross a physical newline between the macro
  name and `(`. A line-oriented expander must collect that next line only when
  it begins an argument list, or Debian glibc attribute macros stay unexpanded.
- Function-pointer fields in CPython type objects may be initialized as
  `&function`. Global initializer code needs to classify those as relocatable
  addresses even when the internal type spelling starts with a function op.
- Flexible array members do not make their containing struct unsized for
  `sizeof`. The final array contributes no element storage but can force
  padding before the tail.
- The same flexible-array rule must be applied in member-offset walkers, not
  just in `sizeof`; code often immediately subscripts the flexible tail.
- Array member expressions should not ask for aggregate slot metadata in value
  contexts. They usually decay immediately to an address, and flexible arrays
  cannot provide a finite slot size anyway.
- Global initializers for structs with flexible tails should stop after fixed
  fields when the tail is absent. There is no implicit zero-sized array payload
  to emit.
- Local array initializers are not integer-only. The element store path must use
  the element type's register class, especially for temporary `float[]` and
  `double[]` buffers.
- Conditional aggregate expressions are not addressable as a whole. Assignment
  and initialization paths need to branch first, then copy the selected
  aggregate source into the already-computed destination.
- Register-class normalization belongs at expression entry points. Floating
  contexts often request XMM results from integer literals, identifiers, or
  `sizeof` values before an explicit conversion step can run.
- Passing `configure` once is not enough if early probes ran on a weaker
  backend. Re-run configure after fixing probe-shaped codegen failures, because
  pyconfig compatibility macros like `#define const /**/` can poison later
  full-source compilation.
- String literals are arrays with static storage, not only pointer rvalues.
  Any address path used by subscript, unary `&`, or decay must be able to
  materialize the literal label.
- Local array initialization must dispatch by element type. Record element
  initializer lists need per-element aggregate initialization, not the scalar
  store path.
- Static locals are emitted as data, but their references are bound while
  emitting function bodies. Complete incomplete array bounds during static-local
  collection, before creating the function-scope slot metadata.
- Conditional aggregate call arguments are their own ABI case. The condition
  selects a source aggregate; only after that should the call-lowering path
  read and push register/stack chunks.
- Function-scope compound literals have automatic storage. By-value aggregate
  call lowering should materialize them once in a frame slot and push chunks
  from that slot, or initializer side effects can be duplicated.
- `{0}` for aggregate storage is not an aggregate copy. Local arrays of unions
  can use scalar zero as an element initializer, and the destination storage
  should simply be zeroed.
- Conditional aggregate returns need their own materialization path. Assignment
  and call-argument fixes do not help `return flag ? left : right` unless the
  return lowering also avoids taking the conditional expression address.
- `call().member` on a small returned struct still needs storage. The call
  result lives in ABI return registers, so member-address formation must first
  spill those chunks into a frame slot.
- Incomplete arrays can still appear as extern objects. Identifier lowering
  must check array/aggregate decay before asking for slot size, or `T[]` looks
  like an impossible `T[-1]` object.
- Global pointer constants are often subobject addresses, not just bare symbols
  or direct members. Constant array subscripts need to fold into the relocation
  addend before member offsets are added.
- Conditional aggregate return handling must cover both SysV classes. Small
  returns use scratch plus return registers; large returns write directly into
  the hidden sret pointer.
- C macros expand even in member-name position. A self-reference inside the
  replacement list should be controlled by macro self-disable, not by skipping
  expansion after `.` or `->`.
- Global pointer initializers can rely on array-to-pointer decay of a nested
  global subobject, not only explicit `&subobject`. Fold the lvalue path first,
  then use the resulting relocation for the pointer field.
- A block-scope function prototype is still a function declaration, not an
  automatic object. Slot collection and declaration emission must both skip it.
- Ignoring a memory-class aggregate call result does not remove the ABI result
  path. The caller must still provide hidden sret storage for callee writes.
- CPython per-file flags can be semantically inert for xcc but still mandatory
  for make compatibility. Classify harmless flags before rejecting unknown
  native options.
- Global floating initializers are constant expressions, not just literals.
  Backend data emission needs the same folding surface as runtime expressions
  for arithmetic, casts, and compiler floating builtins.
- Constant expression helpers can be called while resolving declarator type
  specs, before every operand has a sema type-map entry. Fall back to scope
  symbols for `sizeof(local)` instead of indexing the map blindly.
- Macro self-disable is token state, not just recursion stack state. Expanded
  argument tokens can be substituted into outer macro bodies and rescanned, so
  unavailable identifiers must travel with the tokens.
- Static assertions often survive preprocessing inside initializers as comma
  constant expressions. Integer constant folding should treat `(side, value)`
  as the right operand when the side expression is itself constant-only.
- Compiler memory builtins are part of the C compiler contract even when libc
  has the real implementation. Accept them in sema and lower native calls to
  the corresponding libc symbol.
- Statement expressions need frame planning, not just emission support. Any
  local declarations inside `({ ... })` must be discovered before the native
  function prologue is emitted.
- Relocatable pointer initializers can hide behind constant conditionals.
  Fold the condition first and then run the existing lvalue-to-symbol path on
  the selected branch.
- Do not rely on libatomic being present on the target host. If configure adds
  `-latomic`, native atomics still need direct lowering and the link driver may
  need to drop the library when no helper calls remain.
- Link-only driver paths are separate from compile+link paths. If a target
  filters an unsupported library after compiling C inputs, apply the same
  filter when the driver is invoked only over existing object files.
- Unresolved `__builtin_*` references at link are backend bugs, not missing
  libraries. Treat GCC/Clang compiler builtins as target semantics and lower
  them directly, including objects compiled before the final link step.
- Comment preservation must not suppress macro expansion for code before the
  comment. If a line has `MACRO(args); /*` and the block comment closes later,
  expand the prefix before carrying the comment tail forward.
- Expression emitters must honor their declared result register. Address
  formation often asks subexpressions for `rcx`/`rdx`; returning that register
  while leaving the value in `rax` turns later stores into stale-register
  writes.
- On SysV x86_64, variadic arguments do not begin on the stack. `va_start`
  must expose the saved GP/FP argument registers first and only then advance
  through the overflow stack area.
- SysV call alignment is a property of the whole temporary evaluation stack,
  not just the current call's formal stack arguments. Nested argument calls
  must account for earlier pushed arguments before deciding whether to pad.
- SysV `va_list` parameters are pointer-like even when local `va_list` objects
  occupy the full register-save cursor structure. Builtins that consume a
  `va_list` expression must use the pointed storage for parameters and the
  local slot address for automatic objects.
- CPython extension-module builds exercise a wider compile-flag surface than
  the core interpreter. Classify semantically compatible platform flags such
  as `-fPIC` before the native unsupported-option check.
- Array-to-pointer decay applies before casts to integer types, not only before
  casts to pointer types. Remote-debugging code can cast a local `char[]`
  buffer to `uintptr_t` for validation.
- Accepting `-fPIC` is not enough for shared objects. External data references
  in text need GOT loads on ELF x86_64, or extension-module links fail with
  `R_X86_64_PC32` relocation diagnostics.
- System math macros can expand to compiler builtins even when the C source
  never names them directly. Keep sema's builtin table aligned with glibc
  macro output, including predicates such as `__builtin_signbit` and
  `__builtin_isnormal`.
- A backend can preserve `long double` layout while still lowering CPython's
  suffixed math constants through a narrower runtime path. Rejecting every
  `1.0L` literal blocks math modules before true x87 support is needed.
- In ELF shared objects, same-object non-static globals are still
  default-visible and preemptible. Treat their text references like external
  data and use GOT loads unless the C storage is static/local.
- x86_64 integer compare instructions do not accept 64-bit immediates. Switch
  lowering for large unsigned case labels must materialize the constant first.
- Function designator addresses are data-like under ELF PIC. A direct call can
  use the normal call relocation, but taking a non-local function's address
  needs a GOT load in shared objects.
- Function-scope tagged records are real scoped type bindings, not recoverable
  from the spelling `union tag` alone. Codegen passes that do not retain sema
  block scopes must rebuild enough tag-scope context before planning nested
  local slots.
- A function-level local-symbol map is not enough for block scopes with
  shadowing. Frame planning should trust syntactic array declarators when an
  inner block reuses an outer pointer name.
- SysV aggregate INTEGER eightbytes can contain odd-sized tails. Treat 3, 5,
  6, and 7-byte chunks as byte-packed register payloads instead of rejecting
  them or widening memory accesses past the object.
- Nested initializer lists inside records are not record-only. Array members
  commonly use `{0}` and should route through the same compound-initializer
  dispatcher as arrays, records, and scalar singletons.
- Static pointer tables often spell subobject addresses as `array + n`, not
  only `&array[n]`. Relocation folding must apply C pointer scaling before
  emitting the byte offset.
- Integer constant folding for static data needs the usual cast surface, not
  just integer-origin expressions. Float-to-integer casts in initializers are
  still constant expressions when the operand is a floating constant.
- Anonymous typedef records can share member names while differing in member
  types or array bounds. Codegen recovery of sema record identities must match
  the member types too, or `sizeof` can under-allocate objects even while
  member access uses larger offsets.
- Compound pointer assignment is pointer arithmetic, not integer arithmetic.
  The stored pointer update must apply element-size scaling just like `p + n`,
  especially when CPython walks typed entry arrays with runtime strides.
- Wide string literal storage has to follow the target element width even for
  ASCII-only contents. Packing `L"..."` as bytes silently breaks early
  bootstrap paths that compare `wchar_t *` strings before Python codecs exist.
- Anonymous typedef record matching should compare codegen-visible member
  types. Sema may already have lowered enum fields to the ABI integer type
  while the syntax body still says `enum`.
- Opaque tagged record pointers still need their tag identity. Even when
  `struct tag` is incomplete, collapsing it to bare `struct` makes anonymous
  parent records impossible to match back to sema.
- Static local scope markers are not stack storage. If a backend uses marker
  slots for C scope tracking, identifier and address emission must redirect
  them to the static data label before ordinary stack-slot handling.
- Frame planning may know a more precise local array type than sema. When a
  backend completes a local `T[]` or unevaluated-bound array for storage,
  later `sizeof(identifier)` must consult the active slot before stale symbol
  metadata.
- Update expressions used as address operands must keep the lvalue address
  storage separate from the expression result register. In `*sp++`, the yielded
  old pointer is the dereference address, while the incremented pointer still
  has to be stored through the original local `sp` slot.
- Function-local symbol maps are not a substitute for scoped declaration
  slots. Under shadowing, frame planning must verify the semantic symbol's
  declarator shape and storage size before reusing it, or a later pointer local
  can be loaded as an integer and corrupt bootstrap objects.
- Codegen stack-depth state has to model runtime paths, not emitted paths.
  Conditional aggregate arguments emit pushes in both branches, but only one
  branch executes; count one branch before deciding whether a later call needs
  an ABI alignment pad.
- Driver defaults are part of the target contract. If CPython is configured
  with `CC="xcc"` on x86_64 Linux, the host default must select the native ELF
  backend; otherwise the build silently depends on an explicit target flag and
  LLVM tooling.
- GCC stack allocation builtins are not linkable runtime calls. Native
  backends must lower `__builtin_alloca` by adjusting the stack pointer inline,
  and preserve ABI alignment for later calls.
- A `for` initializer declaration owns a statement scope. Leaving
  `for (int i = ...)` in the enclosing compound scope can hide an outer
  parameter after the loop; CPython flowgraph then rewrites the wrong
  instruction index and produces invalid bytecode CFG.
- External compiler tools need identity checks, not just paths. Discovering
  `llc` through environment/PATH is useful only if the driver verifies the
  candidate's own help output before trusting a same-name executable.
- Driver flags that affect frontend semantics must be stored in the frontend
  options, not only forwarded for delegated tool invocations.
- Generated-output driver actions need per-input output paths. For `-S` and
  `-c`, an explicit single `-o` with multiple C inputs should fail before any
  output can be overwritten.
- A pure-Python macro-text pre-scan can lose even when it reduces `lex_pp`
  calls. In the CPython cold frontend profile, simple rendered tokens were the
  cheap lexer cases; the expensive fallback strings still dominated while the
  pre-scan added its own full pass.
- CPython already compiles membership in a constant set literal to a frozenset
  constant. Hoisting `name in {"a", ...}` sets by hand is not a meaningful hot
  path optimization unless bytecode/profile evidence says otherwise.
- Avoid assuming that replacing a public list-returning tokenizer with an
  internal tuple-returning helper will help every caller. After macro text reads
  already use cached tuples, a direct macro-replacement tuple helper reduced one
  wrapper call count but made the CPython cold frontend profile worse.
- Compatibility projections inside hot immutable data constructors should avoid
  repeated scans over the same canonical shape. Keep the canonical field intact,
  but derive legacy views such as pointer depth and integer array bounds in one
  pass.
- Tiny helper layers are still measurable when they sit under every preprocessor
  output line. If a helper only destructures an already-validated value into a
  tuple, inline it at the hot append site and leave the standalone helper for
  colder direct callers.
- Do not allocate source-location objects for paths that only need line-map
  coordinates. Keep full `_SourceLocation` construction for diagnostics and
  macro expansion, but pass raw filename/line pairs through output-only paths.
- `pstats.strip_dirs()` can erase the only module identity needed to distinguish
  hot `__init__.py` functions. Keep full paths in machine-readable profiles
  when residual recommendations depend on package/module ownership.
- Once a helper sits under hundreds of thousands of blank/output-line writes,
  preserving its behavior may still require inlining the single-line fast path;
  measure both the helper row and its caller because work can shift from one
  row to the other.
- Do not recollect or reparse a directive after a successful first parse when
  the physical line proves it is a simple single-line directive. Keep
  continuation and block-comment-bearing directives on the normalized path, but
  let the common case reuse the classification already paid for.
- Helper-internal fast paths still pay call overhead at CPython-header scale.
  If the caller can prove a no-op condition with a cheap local check, skip the
  helper call entirely and leave the helper to cover the state-changing paths.
- Reducing lexer call count is not enough evidence for a frontend win. A
  simple macro-replacement token fast path reduced `lex_pp` calls but worsened
  the CPython cold frontend profile, because the added pre-scan did not remove
  the expensive fallback tokenization work.
- Gate speculative parser probes with syntax that cannot produce the probed
  construct. A file-scope `typedef` cannot be a function definition, so parse
  it as a declaration before invoking function-shape lookahead.
- When inlining a hot helper into its caller, judge the caller chain by
  cumulative time and total calls, not only the caller's self time. Moving
  `append_at` work into `process_text` raised `process_text` self time but
  reduced the full preprocessor path.
- Profile noise from one-time library/module loading can obscure a local hot-path
  win.
  Before rejecting a narrow optimization, rerun and compare local rows, total
  call count, and unrelated load/runtime rows separately.
- Callback adapter functions are real work in highly repeated frontend paths.
  If a helper can accept the canonical callable shape directly, avoid allocating
  a forwarding lambda in the wrapper on every call.
- Once a shared helper owns the behavior boundary, hot callers can call it
  directly with cached context instead of paying an object wrapper method on
  every directive. Keep a focused test around wrapper bypasses so the shortcut
  remains intentional.
- A shared helper does not have to own every success path if the caller already
  has the complete state transition locally. Empty `#else`/`#endif` can update
  the conditional stack in `process_text`; keep nonempty tails and error paths
  on the shared helper so diagnostics stay centralized.
- For directive fast paths, make the accepted shape narrower than the language
  shape. Plain ASCII `#ifdef NAME` can skip the shared helper, while comments,
  Unicode names, and malformed tails should fall back so one canonical
  diagnostic/comment-stripping implementation remains in charge.
- Pure-comment conditional tails are still a narrow success shape. Let hot
  `process_text` handle `#else /* ... */` and `#endif // ...` locally, but keep
  trailing tokens and malformed comments on the shared helper so the diagnostic
  contract remains centralized.
- Put conditional-expression shape parsing at the eval boundary, not at every
  directive dispatch site. A `process_text`-level simple `defined` fast path
  made every `#if`/`#elif` pay a pre-scan and worsened the cold frontend
  profile; the helper-level version only runs after branch state proves an
  expression would otherwise be evaluated.
- Cache pure post-expansion expression evaluation, not higher-level condition
  evaluation. Macro expansion, `defined`, and probe operators can depend on the
  current preprocessor state, but the final Python expression string is a pure
  bounded cache key.
- In parser precedence loops, wrapper methods can dominate even when each
  wrapper is tiny. If a recursive expression layer only delegates to a module
  helper, pass the module helper directly through the hot loop and leave the
  public wrapper surface intact for external callers/tests.
- Mypy tracks local variable names across an entire function. In large backend
  methods, reuse names such as `value`, `item`, `index`, or `function` only when
  the type really stays the same; otherwise prefer semantic one-shot names so
  the checker does not merge unrelated branch types.
- EVM function-pointer tests should cover both implicit function designators
  and explicit `&function` addresses. The first proves expression-position
  function names lower to code labels; the second keeps address-of from falling
  back to ordinary object lvalue handling.
- EVM function-pointer storage initializer tests need to execute initcode and
  then call through the deployed runtime. The stored value is a runtime bytecode
  offset, so testing only the initializer evaluator misses label resolution
  against the final assembled runtime.
- EVM aggregate return tests should cover both direct helper locals and
  assignment/function-pointer call flows. Return slots are just source
  addresses for later word-slot copies, so scratch-slot ordering bugs can hide
  unless the right-hand side itself evaluates a helper call.
- EVM function-pointer aggregate parameter tests should let the callee mutate
  its parameter and then read the caller's original record. That distinguishes
  true by-value argument slot copies from accidentally aliasing caller storage
  through the indirect dispatch path.
- In AOT LLVM text emission, branch-local Python temporaries are still SSA
  names. Do not propagate a name assigned only in one `if` arm unless the other
  arm has a dominating previous value, and prefer unique source temporary names
  for unrelated `elif` branches so the emitter does not build useless phi nodes
  with non-dominating incoming values.
- If `ty` calls a `cast(...)` redundant but AOT lowering relied on it for union
  narrowing, fix the lowerer's guard narrowing instead of preserving a
  checker-only cast. Broad `llc` probes catch these gaps because CPython and
  static type checkers can both pass while the AOT IR still carries a union
  record into string or integer operations.
- In bootstrap-critical native paths, avoid tuple structural equality,
  tuple-parameter iteration, direct dict indexing by computed integer object
  ids, and `int(str, base)` unless those forms have focused native coverage.
  CPython can make all of them look harmless while the current AOT runtime may
  lower them to pointer equality, list-style tuple indexing, or incomplete
  string runtime behavior.
- A loop-header phi is not the post-loop value for every exit. A `break` edge
  must contribute the environment at the actual break predecessor; otherwise
  an append or assignment immediately before `break` is silently discarded.
- A test named `llc_parseable` must execute `llc`. Text generation alone can
  miss invalid pointer arithmetic and other LLVM verifier/parser failures in a
  very large real bootstrap module.
- Treat an `unexpected success` as evidence to audit, not as a reason to weaken
  assertions. When the full native behavior/object oracle passes, remove the
  stale expected-failure marker and promote the probe to an ordinary gate.
- Removing a function-name special emitter also removes its private signature
  contract. Replace name-shaped tests with generic ABI/handler assertions so a
  bodyless fallback or reintroduced bypass cannot masquerade as success.
