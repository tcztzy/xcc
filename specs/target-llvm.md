# LLVM Target Contract

## Output

`--target=llvm` emits textual LLVM IR for `-S`. For `-c` or link actions, the
driver lowers that IR with a verified LLVM `llc` and then uses the platform
toolchain as required.

The implementation boundary is `src/xcc/codegen.py` plus the libLLVM-C bindings
in `src/xcc/llvm_api.py`.

## Tool Resolution

- Candidate `llc` paths come from `XCC_LLC`, `LLVM_CONFIG`, or `PATH`.
- A same-name executable is accepted only when its help output identifies LLVM
  `llc`.
- Object lowering passes explicit optimization and file-type options.
- A hardcoded path is not the portable discovery algorithm. On the current
  development machine, validation uses `/opt/homebrew/opt/llvm/bin/llc`.

## IR Requirements

- Recursive code generation reads the builder's actual insertion block; a
  cached assumed block must not survive nested emission.
- The builder is not positioned at the end of a terminated block unless the
  caller explicitly inserts before its terminator.
- LLVM pointer handles accept both Python `None` and a null integer handle.
- Control-flow reproducers must parse and lower successfully through the
  verified `llc`.
- Local and static aggregate scalar initializers zero the aggregate and
  initialize its first member; scalar-to-whole-record bitcasts are forbidden.

## Validation

- V1: On Darwin AArch64, a non-homogeneous record parameter larger than 16
  bytes is passed indirectly at function definitions and calls. A by-value
  argument is copied before either a direct or indirect call.
- V2: On Darwin AArch64, a non-homogeneous record return larger than 16 bytes
  uses the platform indirect-result register at function definitions and
  direct or indirect calls.
- V3: On Darwin AArch64, a record argument that does not fit in the remaining
  argument registers is passed wholly on the stack, never split across the
  final register and the stack.
- V4: A `float` expression passed to a declared `double` parameter is widened
  before the call.
- V5: On Darwin AArch64, a non-homogeneous record return of at most 16 bytes is
  packed into the platform integer aggregate representation at definitions and
  direct or indirect calls.
- V6: Record bit-fields use the semantic target layout; signed reads extend the
  declared width, and simple, compound, and update writes mask and merge without
  changing adjacent fields.
- V7: Compiler-generated fixed-size temporaries are allocated in the function
  entry block, so evaluating record ABI coercions or other temporaries in a loop
  does not grow the stack. Explicit `__builtin_alloca` remains dynamic.
- V8: A local declaration has one entry-block allocation. Lexical scope lookup
  must not be implemented by pre-allocating a second, unused copy.

## Acceptance

Tests cover IR text, `llc` verification and invocation, object generation, and
executable behavior for semantics affected by a change.
