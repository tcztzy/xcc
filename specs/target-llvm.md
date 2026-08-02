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

## Acceptance

Tests cover IR text, `llc` verification and invocation, object generation, and
executable behavior for semantics affected by a change.
