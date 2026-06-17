# CHANGELOG

## Current

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
