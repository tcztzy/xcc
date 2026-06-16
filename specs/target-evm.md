# EVM Target Spec

## §G GOAL
The `evm` target emits Ethereum legacy runtime bytecode for a freestanding C
subset, with ABI-dispatched exported functions and no dependency on LLVM,
Solidity, or external assemblers.

## §C CONSTRAINTS
- `--target=evm` selects this target explicitly.
- Host defaults remain unchanged; EVM is never selected implicitly.
- Runtime implementation uses only the Python standard library.
- Output uses legacy EVM bytecode, not EOF.
- `-S` emits readable EVM opcode assembly with `.evmasm` default output.
- `-c` emits lowercase hex runtime bytecode with `.bin` default output.
- Link action is unsupported because EVM has no native `.o`/executable link
  model.
- The C surface is a freestanding integer subset with EVM word pointers,
  fixed local arrays, dynamic ABI word arrays, loops, and simple storage
  aggregates, signed scalar arithmetic, integer conversions, plus short-circuit
  and selected-branch scalar expressions, switch dispatch, target word-layout
  `sizeof` / `_Alignof` / `__builtin_offsetof`, character literals, direct
  internal helper calls, GNU statement expressions, enum constants, and
  type-only generic selection helpers, fixed-array and record compound
  literals, anonymous union member layout/access, word-backed record
  bit-fields, unnamed bit-field padding, char-word string literals, aggregate
  assignment, designated aggregate initializers, direct and indirect
  `goto`/label control flow,
  fixed-prototype function pointer calls to same-translation-unit helpers,
  internal helpers that accept function-pointer and record parameters and
  return word pointers, function pointers, or records, block-scope helper
  prototypes, no-op declarations or statements, and block-scope static local
  storage.
- Ethereum ABI selectors use Keccak-256, not FIPS SHA3-256.

## §I INTERFACES
- cmd: `xcc --target=evm -S source.c -o source.evmasm` → EVM opcode assembly.
- cmd: `xcc --target=evm -c source.c -o source.bin` → hex runtime bytecode.
- cmd: `xcc --target=evm --evm-initcode -c source.c -o source.init.bin` →
  hex deployment initcode bytecode.
- file: `src/xcc/evm.py` → Keccak-256 selector helper, legacy EVM assembler,
  and minimal AST-to-EVM lowering.
- asm: implicit zero constants use `PUSH0`; explicit push widths for labels
  and ABI selectors stay fixed.
- builtin: `__builtin_evm_sload(unsigned int slot)` → storage word load.
- builtin: `__builtin_evm_sstore(unsigned int slot, unsigned int value)` →
  storage word store.
- builtin: `__builtin_evm_addmod(__evm_uint256 a, __evm_uint256 b,
  __evm_uint256 n)`, `__builtin_evm_mulmod(__evm_uint256 a,
  __evm_uint256 b, __evm_uint256 n)`, and
  `__builtin_evm_exp(__evm_uint256 base, __evm_uint256 exponent)` → native EVM
  modular arithmetic and exponentiation opcodes.
- builtin: `__builtin_evm_byte(__evm_uint256 index, __evm_uint256 value)` →
  native EVM byte extraction opcode.
- builtin: `__builtin_evm_signextend(__evm_uint256 index,
  __evm_uint256 value)` → native EVM sign extension opcode.
- builtin: `__builtin_evm_caller()` → caller address word.
- builtin: `__builtin_evm_callvalue()` → call value word.
- builtin: `__builtin_evm_address()`, `__builtin_evm_origin()`,
  `__builtin_evm_gasprice()`, `__builtin_evm_coinbase()`,
  `__builtin_evm_timestamp()`, `__builtin_evm_number()`,
  `__builtin_evm_prevrandao()`, `__builtin_evm_gaslimit()`,
  `__builtin_evm_chainid()`, `__builtin_evm_selfbalance()`,
  `__builtin_evm_basefee()`, `__builtin_evm_blobbasefee()`, and
  `__builtin_evm_gas()` → native EVM environment/block/gas/blob opcodes.
- builtin: `__builtin_evm_blobhash(__evm_uint256 index)` → native EVM blob
  versioned hash query opcode.
- builtin: `__builtin_evm_balance(__evm_address address)`,
  `__builtin_evm_blockhash(__evm_uint256 number)`,
  `__builtin_evm_extcodesize(__evm_address address)`, and
  `__builtin_evm_extcodehash(__evm_address address)` → native EVM account and
  block query opcodes.
- builtin: `__builtin_evm_extcodecopy(__evm_address address,
  __evm_uint256 *dst, __evm_uint256 offset, __evm_uint256 len)` → external
  account code copy opcode.
- builtin: `__builtin_evm_calldatasize()`,
  `__builtin_evm_calldataload(__evm_uint256 offset)`, and
  `__builtin_evm_calldatacopy(__evm_uint256 *dst, __evm_uint256 offset,
  __evm_uint256 len)` → raw calldata size/load/copy opcodes.
- builtin: `__builtin_evm_returndatasize()` and
  `__builtin_evm_returndatacopy(__evm_uint256 *dst, __evm_uint256 offset,
  __evm_uint256 len)` → prior-call return-data size/copy opcodes.
- builtin: `__builtin_evm_create(__evm_uint256 value, __evm_uint256 *init,
  __evm_uint256 init_len)` → contract creation opcode with explicit initcode
  memory range.
- builtin: `__builtin_evm_create2(__evm_uint256 value, __evm_uint256 *init,
  __evm_uint256 init_len, __evm_uint256 salt)` → deterministic contract
  creation opcode with explicit initcode memory range and salt.
- builtin: `__builtin_evm_call(__evm_uint256 gas, __evm_address address,
  __evm_uint256 value, __evm_uint256 *in, __evm_uint256 in_len,
  __evm_uint256 *out, __evm_uint256 out_len)` → message call opcode with
  explicit input and output memory ranges.
- builtin: `__builtin_evm_callcode(__evm_uint256 gas, __evm_address address,
  __evm_uint256 value, __evm_uint256 *in, __evm_uint256 in_len,
  __evm_uint256 *out, __evm_uint256 out_len)` → legacy message call-code opcode
  with explicit input and output memory ranges.
- builtin: `__builtin_evm_staticcall(__evm_uint256 gas, __evm_address address,
  __evm_uint256 *in, __evm_uint256 in_len, __evm_uint256 *out,
  __evm_uint256 out_len)` → static message call opcode with explicit input and
  output memory ranges.
- builtin: `__builtin_evm_delegatecall(__evm_uint256 gas,
  __evm_address address, __evm_uint256 *in, __evm_uint256 in_len,
  __evm_uint256 *out, __evm_uint256 out_len)` → delegate message call opcode
  with explicit input and output memory ranges.
- builtin: `__builtin_evm_codesize()` and
  `__builtin_evm_codecopy(__evm_uint256 *dst, __evm_uint256 offset,
  __evm_uint256 len)` → runtime code size/copy opcodes.
- builtin: `__builtin_evm_mload(__evm_uint256 *ptr)` and
  `__builtin_evm_mstore(__evm_uint256 *dst, __evm_uint256 value)` → native EVM
  word memory load/store opcodes.
- builtin: `__builtin_evm_mcopy(__evm_uint256 *dst, __evm_uint256 *src,
  __evm_uint256 len)` → native EVM byte memory copy opcode.
- builtin: `__builtin_evm_mstore8(__evm_uint256 *dst, __evm_uint256 value)`
  and `__builtin_evm_msize()` → native single-byte memory store and active
  memory size opcodes.
- builtin: `__builtin_evm_tload(__evm_uint256 key)` and
  `__builtin_evm_tstore(__evm_uint256 key, __evm_uint256 value)` → native EVM
  transient storage opcodes.
- builtin: `__builtin_evm_pc()` → current runtime bytecode position via the
  native EVM program-counter opcode.
- builtin: `__builtin_evm_revert()` → empty revert.
- builtin: `__builtin_evm_revert_data(__evm_uint256 *ptr, __evm_uint256 len)`
  → raw EVM memory revert payload.
- builtin: `__builtin_evm_return(__evm_uint256 *ptr, __evm_uint256 len)` →
  raw EVM memory return.
- builtin: `__builtin_evm_stop()` and `__builtin_evm_invalid()` → terminal
  stop and invalid opcodes.
- builtin: `__builtin_evm_selfdestruct(__evm_address beneficiary)` →
  self-destruct opcode with an explicit beneficiary address.
- builtin: `__builtin_evm_log0` through `__builtin_evm_log4` → event logs with
  zero to four topics and one 32-byte data word.
- builtin: `__builtin_evm_log0_data` through `__builtin_evm_log4_data` → event
  logs with zero to four topics and an explicit memory byte range.
- builtin: `__builtin_evm_keccak256(__evm_uint256 *ptr, __evm_uint256 len)` →
  Keccak-256 hash of an EVM memory byte range via the native `SHA3` opcode.
- builtin: `__builtin_evm_return_array(__evm_uint256 *ptr, __evm_uint256 len)`
  → ABI dynamic `uint256[]` return payload.
- type: `__evm_uint256` → ABI `uint256` scalar word.
- type: `__evm_address` → ABI `address` scalar word.
- abi: pointer parameters to EVM word scalar types map to dynamic ABI arrays
  such as `uint256[]`; elements are copied into EVM memory with the pointee
  integer conversion before function body execution. Exported functions may not
  return pointer values through the ABI.
- call: function designators and `&function` addresses for same-translation-unit
  fixed-prototype helpers lower to internal EVM jump labels; function pointer
  calls dispatch through matching local function signatures and copy word or
  aggregate arguments through planned call slots. Internal helpers may accept
  word-valued parameters, including function pointer values, and may accept
  record or union parameters by copying aggregate word slots into the callee
  frame. They may return word pointer or function pointer values for later use
  by callers, or return record/union values by copying aggregate word slots
  through the callee return frame.
- decl: block-scope function prototypes for same-translation-unit helpers are
  declarations only; they allocate no local memory and do not shadow direct
  helper calls.
- api: `generate_evm_initcode(result)` → legacy deployment bytecode that
  initializes supported storage globals then returns runtime bytecode.
- initcode: function pointer storage initializers may use function designators,
  `&function`, or constant conditionals selecting between them; deployment
  bytecode stores the matching runtime jump offset.
- storage: file-scope scalar integer and aggregate variables map to storage
  slots in declaration/member order, with record bit-fields backed by one word
  slot, unnamed bit-fields treated as padding, and named bit-fields masked on
  load/store/initialization; runtime bytecode rejects initialized storage
  globals while initcode supports scalar and simple aggregate initializers,
  including fixed-array index and record field designators plus char-array
  string literal initializers. Block-scope static locals use the same
  persistent storage slot model.

## §V INVARIANTS
V291: EVM target ! emits legacy runtime bytecode directly; LLVM IR, `llc`,
`solc`, and platform assemblers ⊥.
V292: EVM `-S` ! writes readable opcode assembly and never invokes external
tools.
V293: EVM `-c` ! writes hex runtime bytecode and never invokes external tools.
V294: EVM link action ! fails with deterministic driver diagnostics.
V295: EVM ABI selectors ! use Ethereum Keccak-256; `hashlib.sha3_256` ⊥.
V296: EVM unsupported C constructs ! fail with `XCC-EVM-0001` diagnostics
instead of falling back to another target.
V297: EVM storage builtins ! lower to `SLOAD`/`SSTORE` opcodes without requiring
Solidity or host libraries.
V298: EVM loop control ! lowers `while`, `do while`, `for`, `break`, and
`continue` through explicit jump labels.
V299: EVM environment/log builtins ! lower caller, callvalue, contract/block/gas
environment queries, account/code/blockhash queries, empty revert, and LOG0-LOG4
operations to native opcodes without external tools.
V300: EVM ABI scalar extensions ! map `__evm_uint256` to `uint256` and
`__evm_address` to `address` selectors while preserving stdlib-only parsing and
sema.
V301: EVM file-scope scalar storage ! maps deterministic declaration-order
slots to `SLOAD`/`SSTORE`; runtime bytecode still rejects initialized storage
globals with `XCC-EVM-0001`.
V302: EVM memory pointers and fixed local arrays ! use explicit 32-byte word
slots with `MLOAD`/`MSTORE` for dereference, subscript, pointer arithmetic, and
address-of lowering.
V303: EVM ABI pointer parameters to word scalar types ! map to dynamic ABI
arrays, use matching `T[]` selectors, and copy calldata elements into memory
before executing C statements.
V304: EVM dynamic array returns ! use `__builtin_evm_return_array` to emit an
ABI dynamic `uint256[]` payload directly from EVM memory.
V305: EVM initcode ! emits legacy creation bytecode directly, initializes
scalar storage globals with `SSTORE`, copies runtime code with `CODECOPY`, and
uses no external tools.
V306: EVM aggregate storage ! maps simple struct members to deterministic
declaration-order storage slots and lowers member `SLOAD`/`SSTORE` directly.
V307: EVM scalar control expressions ! lower `&&`, `||`, `?:`, and comma
expressions with explicit jumps so skipped branches do not run side effects.
V308: EVM signed integer operators ! use signed EVM opcodes for signed
comparison, division, modulo, and right shift after C integer conversions.
V309: EVM integer conversions ! truncate unsigned scalar results, sign-extend
signed scalar results, and normalize `_Bool` to 0/1 at casts, scalar stores,
returns, and integer expression result boundaries.
V310: EVM direct internal function calls ! lower same-translation-unit function
calls to internal jump labels with per-function memory frames, return-PC slots,
and return-value slots; static helpers remain absent from the ABI dispatcher.
V311: EVM `sizeof` and `_Alignof` ! lower to constants from the target's
32-byte word-object layout without evaluating expression operands.
V312: EVM `switch` statements ! lower case/default dispatch through explicit
jump labels, preserving fallthrough and making `break` target the switch end.
V313: EVM character literals ! lower ordinary, escaped, hexadecimal, and octal
character constants through the shared C escape decoder for runtime expressions
and integer constant contexts such as `case` labels.
V314: EVM `__builtin_offsetof` ! lowers to byte constants from the target's
32-byte word-object aggregate layout, including nested member paths.
V315: EVM type-only selection helpers ! lower `__builtin_types_compatible_p`
to 0/1 constants and `_Generic` to only the selected association expression
without evaluating the control expression.
V316: EVM GNU statement expressions ! lower embedded statements in order and
leave the final expression-statement value on the stack as the expression
result.
V317: EVM direct `goto` and labels ! lower to function-copy-local EVM labels so
ABI and internal helper bodies cannot cross-jump into each other.
V318: EVM label addresses and indirect `goto` ! lower `&&label` to the current
function-copy-local EVM `JUMPDEST` offset and `goto *expr` to an indirect
`JUMP`.
V319: EVM scalar, fixed-array, and record compound literals plus local record
initializers ! allocate function-frame memory slots during layout planning,
initialize them with word stores, zero omitted aggregate members, and lower
scalar values, array decay, member access, and assignable lvalue uses from that
storage.
V320: EVM string literals ! decode C escape sequences into char-word memory
slots, support local char-array initialization, and lower expression-position
string literals to planned frame addresses with null terminators.
V321: EVM aggregate assignment ! copies record storage by word slot across
memory and storage address spaces, preserving source independence after the
assignment.
V322: EVM initcode aggregate storage initialization ! flattens scalar, fixed
array, and simple record initializer lists into declaration-order storage slot
stores before returning runtime bytecode.
V323: EVM designated aggregate initializers ! lower fixed-array index/range
and record field designators to word-object local memory offsets and initcode
storage slot offsets, with omitted aggregate elements remaining zeroed.
V324: EVM no-op declarations/statements ! lower null statements, block-scope
typedef declarations, and semantically checked `_Static_assert` declarations to
no bytecode while preserving surrounding control flow.
V325: EVM storage char-array string initializers ! decode C string literal
escapes, append/pad null terminators, and flatten each char-word unit to
initcode storage slots.
V326: EVM block-scope static locals ! allocate persistent storage slots,
initialize supported constant initializers through initcode, zero-initialize
omitted static storage, and skip per-call frame initialization.
V327: EVM enum constants ! lower file-scope and block-scope enum constants in
runtime expressions and integer constant contexts such as `switch` case values.
V328: EVM pointer subtraction ! subtracts memory addresses and divides by the
word-object element stride to produce a C pointer difference.
V329: EVM ABI decoding ! checks calldata size for static argument heads and
dynamic `uint256[]` payloads, reverting truncated calls instead of decoding
missing words as zero.
V330: EVM dynamic ABI offsets ! reject offsets that point before the end of
the static argument head or are not 32-byte aligned before copying dynamic
array payloads.
V331: EVM Keccak memory hashing ! lowers `__builtin_evm_keccak256(ptr, len)` to
native `SHA3`, hashing the exact byte range in EVM memory.
V332: EVM raw calldata builtins ! lower `CALLDATASIZE`, `CALLDATALOAD`, and
`CALLDATACOPY` so C code can inspect and copy raw calldata bytes beyond ABI
decoded parameters.
V333: EVM runtime code builtins ! lower `CODESIZE` and `CODECOPY` so C code can
inspect and copy bytes from its deployed runtime bytecode.
V334: EVM external code copy builtin ! lowers `EXTCODECOPY` so C code can copy
bytes from another account's runtime code into EVM memory by address, offset,
and length.
V335: EVM return-data builtins ! lower `RETURNDATASIZE` and `RETURNDATACOPY`
so C code can inspect and copy prior-call return bytes into EVM memory.
V336: EVM message call builtin ! lowers `CALL` so C code can pass gas, target
address, value, input memory range, and output memory range while receiving the
native success status word.
V337: EVM static message call builtin ! lowers `STATICCALL` so C code can pass
gas, target address, input memory range, and output memory range while
receiving the native success status word without a value argument.
V338: EVM delegate message call builtin ! lowers `DELEGATECALL` so C code can
pass gas, target address, input memory range, and output memory range while
receiving the native success status word and preserving current call context.
V339: EVM legacy call-code builtin ! lowers `CALLCODE` so C code can pass gas,
target address, value, input memory range, and output memory range while
receiving the native success status word.
V340: EVM contract creation builtin ! lowers `CREATE` so C code can pass value
and an initcode memory range while receiving the created contract address word.
V341: EVM deterministic contract creation builtin ! lowers `CREATE2` so C code
can pass value, an initcode memory range, and a salt while receiving the created
contract address word.
V342: EVM self-destruct builtin ! lowers `SELFDESTRUCT` so C code can terminate
execution with an explicit beneficiary address.
V343: EVM modular arithmetic and exponent builtins ! lower `ADDMOD`, `MULMOD`,
and `EXP` so C code can request native EVM arithmetic semantics that are not
equivalent to ordinary wrapped C operators.
V344: EVM byte and memory-size builtins ! lower `BYTE`, `MSTORE8`, and `MSIZE`
so C code can extract a byte from a word, write one byte to EVM memory, and
query active memory size.
V345: EVM raw memory, sign-extension, and program-counter builtins ! lower
`MLOAD`, `MSTORE`, `SIGNEXTEND`, and `PC` so C code can request those native
stack operations directly.
V346: EVM transient storage, memory-copy, and blob builtins ! lower `TLOAD`,
`TSTORE`, `MCOPY`, `BLOBHASH`, and `BLOBBASEFEE` so C code can use Cancun-era
legacy bytecode opcodes directly.
V347: EVM zero constant pushes ! use `PUSH0` when no explicit push width is
required while preserving fixed-width label and selector pushes.
V348: EVM terminal builtins ! lower raw `RETURN`, `STOP`, and `INVALID` so C
code can terminate execution without going through the normal ABI return path.
V349: EVM raw revert and log data builtins ! lower memory byte ranges for
`REVERT` and `LOG0` through `LOG4` so C code can emit native payload slices
without staging a single 32-byte word wrapper.
V350: EVM driver initcode output ! `--target=evm --evm-initcode -c` writes
deployment creation bytecode from `generate_evm_initcode`, defaults to
`.init.bin`, and requires the explicit EVM compile action so non-EVM targets
and EVM assembly output cannot silently ignore it.
V352: EVM function pointer calls ! lower same-translation-unit fixed-prototype
function designators and `&function` addresses to internal jump labels, then
dispatch indirect calls through matching signatures using saved target and
argument slots.
V353: EVM function pointer storage initcode ! resolves function designator and
`&function` storage initializers to assembled runtime jump offsets before
emitting deployment-time `SSTORE`s.
V354: EVM conditional function pointer storage initcode ! folds constant
conditional initializers before resolving the selected helper label to an
assembled runtime jump offset.
V355: EVM block-scope helper prototypes ! allocate no local storage and preserve
direct helper-call lowering for same-translation-unit functions.
V356: EVM internal helper function pointer returns ! preserve selected helper
labels as word return values that callers can indirect-call.
V357: EVM internal helper word pointer returns ! preserve memory pointer words
across return slots while exported ABI functions still reject pointer returns.
V358: EVM internal helper word parameters ! validate static helper parameters as
backend word values instead of exported ABI parameters, including function
pointer parameters that can be indirect-called.
V359: EVM internal helper record parameters ! copy aggregate word slots into the
callee frame for direct same-translation-unit helper calls while leaving the
exported ABI aggregate-free.
V360: EVM internal helper record returns ! allocate aggregate return slots in
the callee frame and copy record/union word slots into caller locals,
assignments, member access, and function pointer return-call paths while
leaving the exported ABI aggregate-free.
V361: EVM function pointer record parameters ! allocate aggregate argument slots
for fixed-prototype indirect calls and copy record/union parameters by value
into the selected callee frame while leaving the exported ABI aggregate-free.
V362: EVM dynamic ABI array element conversions ! normalize calldata words to
the pointer element type while copying dynamic ABI arrays into EVM memory, so
non-`uint256` arrays match scalar ABI parameter conversion semantics.
V363: EVM anonymous union members ! include anonymous record members in
word-slot aggregate layout, recursively resolve promoted member accesses, and
lower positional local initializers for anonymous union members.
V364: EVM record bit-fields ! lower named record bit-field members as
word-backed slots, truncating local memory and storage reads/writes plus
initcode storage initializers to the declared bit width.
V365: EVM unnamed record bit-fields ! treat unnamed bit-fields as padding slots
and skip them during positional local and initcode storage record
initialization.

## §T TASKS
id|status|task|cites
T26|x|add explicit `evm` driver target, `.evmasm`/`.bin` outputs, and link rejection|V291,V292,V293,V294,I.cmd
T27|x|add stdlib-only Keccak-256 selector helper and legacy EVM assembler|V291,V295,I.file
T28|x|lower ABI-dispatched scalar integer functions plus `sload`/`sstore` builtins|V296,V297,I.builtin
T29|x|expand EVM target beyond scalar integer code to memory pointers, richer ABI encoding, deployable initcode, and aggregate storage layout|V302,V303,V304,V305,V306,I.builtin,I.api,I.storage
T30|x|lower EVM loops, caller/callvalue/revert/LOG0-LOG4 builtins, and `__evm_uint256`/`__evm_address` ABI scalar types|V298,V299,V300,I.builtin
T31|x|map EVM file-scope scalar integer variables to deterministic storage slots and reject initialized storage globals|V301,I.storage
T32|x|lower EVM logical short-circuit, conditional, and comma expressions with side-effect ordering|V307
T33|x|lower EVM signed scalar comparison, division, modulo, and arithmetic right shift|V308
T34|x|lower EVM integer casts, scalar store conversions, returns, and expression-width normalization|V309
T35|x|lower same-translation-unit EVM helper calls with isolated function frames and internal returns|V310
T36|x|lower EVM `sizeof` and `_Alignof` constants for word-object scalar, pointer, array, and aggregate layout|V311
T37|x|lower EVM `switch`/`case`/`default` dispatch with fallthrough and switch-scoped `break`|V312
T38|x|lower EVM character literals in scalar expressions and switch case constants|V313
T39|x|lower EVM `__builtin_offsetof` constants for simple and nested record members|V314
T40|x|lower EVM `__builtin_types_compatible_p` and `_Generic` selection expressions|V315
T41|x|lower EVM GNU statement expressions with local declarations and final expression results|V316
T42|x|lower EVM direct `goto` and labels without ABI/internal label collisions|V317
T43|x|lower EVM label addresses and indirect `goto` through EVM jump offsets|V318
T44|x|lower EVM scalar, fixed-array, and record compound literals plus local record initializers using planned word memory storage|V319
T45|x|lower EVM char-word string literals for local array initializers and pointer expressions|V320
T46|x|lower EVM record assignment through word-slot copies across memory and storage|V321
T47|x|lower EVM initcode aggregate storage initializers for fixed arrays and simple records|V322
T48|x|lower EVM designated aggregate initializers for local memory and initcode storage aggregates|V323
T49|x|lower EVM no-op declarations and statements without rejecting valid function bodies|V324
T50|x|lower EVM initcode storage char-array initializers from string literals|V325
T51|x|lower EVM block-scope static local variables to persistent storage slots|V326
T52|x|lower EVM enum constants in expressions and case-value constant evaluation|V327
T53|x|lower EVM pointer subtraction as element-count differences|V328
T54|x|reject truncated EVM ABI calldata before scalar or dynamic-array decoding|V329
T55|x|validate EVM dynamic ABI array offsets before payload decoding|V330
T56|x|lower the full EVM LOG0-LOG4 builtin family with topic-order tests|V299
T57|x|lower EVM Keccak memory hashing through the native SHA3 opcode|V331
T58|x|lower zero-argument EVM environment, block, and gas opcode builtins|V299
T59|x|lower EVM BALANCE, BLOCKHASH, EXTCODESIZE, and EXTCODEHASH query builtins|V299
T60|x|lower EVM raw calldata size/load/copy builtins|V332
T61|x|lower EVM runtime code size/copy builtins|V333
T62|x|lower EVM external account code copy builtin|V334
T63|x|lower EVM return-data size/copy builtins|V335
T64|x|lower EVM external message call builtin|V336
T65|x|lower EVM static external message call builtin|V337
T66|x|lower EVM delegate external message call builtin|V338
T67|x|lower EVM legacy call-code builtin|V339
T68|x|lower EVM contract creation builtin|V340
T69|x|lower EVM deterministic contract creation builtin|V341
T70|x|lower EVM self-destruct builtin|V342
T71|x|lower EVM native modular arithmetic and exponent builtins|V343
T72|x|lower EVM byte extraction and single-byte memory-size builtins|V344
T73|x|lower EVM raw memory, sign-extension, and program-counter builtins|V345
T74|x|lower EVM transient storage, memory-copy, and blob builtins|V346
T75|x|emit EVM PUSH0 for implicit zero constants|V347
T76|x|lower EVM raw return, stop, and invalid terminal builtins|V348
T77|x|lower EVM raw revert payload and LOG0-LOG4 memory-range builtins|V349
T78|x|add explicit EVM CLI deployment initcode output|V350,I.cmd
T80|x|lower EVM function pointer calls to same-translation-unit fixed-prototype helpers|V352,I.call
T81|x|initialize EVM storage function pointers from runtime function labels in initcode|V353,I.initcode
T82|x|fold constant conditional EVM storage function pointer initializers before initcode label resolution|V354,I.initcode
T83|x|treat EVM block-scope helper prototypes as no-op declarations for direct helper calls|V355,I.call
T84|x|allow EVM internal helpers to return function pointer values for later indirect calls|V356,I.call
T85|x|allow EVM internal helpers to return word pointer values while rejecting exported ABI pointer returns|V357,I.call,I.abi
T86|x|allow EVM internal helpers to accept function pointer word parameters without exposing them through the ABI|V358,I.call,I.abi
T87|x|copy EVM internal helper record and union parameters by value for direct helper calls|V359,I.call
T88|x|copy EVM internal helper record and union return values through aggregate return slots|V360,I.call
T89|x|copy EVM function pointer record and union parameters by value through indirect-call argument slots|V361,I.call
T90|x|convert EVM dynamic ABI array elements to the pointer element type during calldata copy|V362,I.abi
T91|x|lower EVM anonymous union member layout, promoted access, and positional local initialization|V363,I.storage
T92|x|lower EVM word-backed record bit-field member access and initcode storage initialization|V364,I.storage
T93|x|skip EVM unnamed record bit-field padding during local and initcode storage initialization|V365,I.storage

## §B BUGS
id|date|cause|fix
