# EVM Target Contract

## Goal and Output

`--target=evm` compiles a freestanding C subset directly to Ethereum legacy EVM
bytecode through `src/xcc/evm.py`. It never invokes LLVM, `llc`, Solidity, or a
platform assembler.

| Action | Output |
| --- | --- |
| `-S` | readable opcode assembly, default suffix `.evmasm` |
| `-c` | lowercase hex runtime bytecode, default suffix `.bin` |
| `--evm-initcode -c` | lowercase hex deployment bytecode, default suffix `.init.bin` |
| link | deterministic unsupported-action diagnostic |

The EVM target is explicit and never a host default. Output uses legacy
bytecode, not EOF.

## C and ABI Model

- Scalars are EVM words with C signedness and width conversions.
  `__evm_uint256` maps to ABI `uint256`; `__evm_address` maps to ABI `address`.
- Exported fixed-prototype functions are selected with Ethereum Keccak-256.
  FIPS SHA3-256 is not selector-compatible.
- Pointer parameters to supported word scalar types map to dynamic ABI arrays.
  Calldata bounds, alignment, head offsets, payload lengths, and element
  conversions are validated before copying to EVM memory.
- Exported functions do not return raw pointers. The explicit return-array
  builtin emits ABI dynamic `uint256[]` data.
- Internal same-translation-unit helpers may take and return word values,
  pointers, function pointers, records, and unions through planned frames.
  Direct and signature-compatible indirect calls preserve argument and return
  slots. Block-scope helper prototypes allocate no storage.
- Supported C includes scalar and pointer expressions, fixed arrays, records
  and unions, bit-fields, aggregate assignment and initialization, loops,
  switch, direct and indirect goto, compound literals, enum constants,
  statement expressions, `sizeof`, `_Alignof`, `offsetof`, and type-only
  generic selection.
- Unsupported constructs fail with deterministic `XCC-EVM-0001` diagnostics;
  another target must never be used as fallback.

## Memory, Storage, and Layout

- Memory pointers use byte addresses; ordinary target objects occupy 32-byte
  word slots. Pointer arithmetic, `sizeof`, alignment, and subobject offsets use
  this target model consistently.
- File-scope objects and block-scope statics receive deterministic persistent
  storage slots. Records, fixed arrays, named bit-fields, unnamed padding, and
  designated initializers flatten in declaration/layout order.
- Runtime bytecode rejects initialized persistent storage that requires
  deployment work. Initcode applies supported scalar, aggregate, string, and
  function-label initializers before returning the runtime code.
- Local aggregates live in planned EVM memory and are zero-filled before
  positional or designated initialization.

## Builtin Families

All builtins lower directly to the corresponding EVM operation and use explicit
memory byte ranges where applicable.

| Family | Builtins or operations |
| --- | --- |
| Storage | `sload`, `sstore`, `tload`, `tstore` |
| Memory | `mload`, `mstore`, `mstore8`, `msize`, `mcopy`, `keccak256` |
| Calldata and code | `calldatasize`, `calldataload`, `calldatacopy`, `codesize`, `codecopy`, `extcodesize`, `extcodehash`, `extcodecopy` |
| Return data | `returndatasize`, `returndatacopy` |
| Calls and creation | `call`, `callcode`, `staticcall`, `delegatecall`, `create`, `create2` |
| Arithmetic | `addmod`, `mulmod`, `exp`, `byte`, `signextend` |
| Environment | `address`, `balance`, `origin`, `caller`, `callvalue`, `gasprice`, `coinbase`, `timestamp`, `number`, `prevrandao`, `gaslimit`, `chainid`, `selfbalance`, `basefee`, `blobhash`, `blobbasefee`, `blockhash`, `gas`, `pc` |
| Logs | `log0` through `log4`, with word and explicit-range forms |
| Termination | raw `return`, `revert`, `stop`, `invalid`, `selfdestruct` |

The public spellings use the existing `__builtin_evm_*` prefix. Implicit zero
constants use `PUSH0`; labels and ABI selectors retain fixed explicit push
widths.

## Control and Value Semantics

- `&&`, `||`, conditional, comma, loop, switch, and selected-branch constructs
  preserve C side-effect order through explicit jump labels.
- Signed comparison, division, modulo, and right shift use signed EVM
  operations after C conversions. Narrow integers truncate or sign-extend, and
  `_Bool` normalizes to zero or one at value boundaries.
- Function-local label copies cannot cross-jump between ABI dispatcher and
  internal helper bodies.
- Aggregate copies preserve source independence across memory and storage.
- String and character escapes use the shared C decoder and include required
  null storage.

## Acceptance

Tests cover readable assembly, exact bytecode execution, ABI selector and
decoder boundaries, malformed calldata, memory/storage effects, topic order,
internal calls, initcode behavior, and deterministic rejection. Opcode text
alone is insufficient for stateful or arithmetic semantics.
