# XCC

XCC is a working C11 compiler written in Python. It uses only the Python
standard library at runtime and can be used as a `CC` driver for real build
systems: CPython builds with `CC="xcc" ./configure && make` on the supported
targets. The implementation is still compact and readable, but the validation
bar is CPython-scale C rather than toy examples.

## Pipeline

```
.c → [preprocessor → lexer → parser → sema] → target assembly
   → assembler/linker when object or executable output is requested
```

- `--target=llvm`: emit LLVM IR and lower objects through a discovered LLVM
  `llc` executable
- `--target=aarch64-apple-darwin`: emit native Darwin AArch64 assembly directly
- `--target=x86_64-linux-gnu`: emit native ELF x86_64 SysV assembly directly
- `--target=evm`: emit Ethereum legacy EVM opcode assembly or hex runtime
  bytecode for a freestanding integer/pointer C subset, including
  ABI-dispatched scalar and dynamic word-array functions with calldata bounds,
  offset validation, and element conversions, loop control flow, word-pointer
  arithmetic and differences, signed scalar operations, native modular
  arithmetic/exponent builtins, integer conversions, short-circuit scalar
  expressions, switch
  dispatch,
  `sizeof`/`_Alignof`/`__builtin_offsetof` constants, character literals, enum
  constants, `_Generic`/`__builtin_types_compatible_p`, GNU statement
  expressions, fixed-array and record compound literals, anonymous union member
  layout/access, word-backed record bit-fields and unnamed bit-field padding,
  char-word string literals, aggregate assignment, designated aggregate
  initializers, direct and indirect `goto`/labels, direct internal helper calls,
  fixed-prototype
  function pointer calls with word and aggregate parameters to
  same-translation-unit helpers, internal helpers accepting function-pointer and
  record/union parameters and returning word/function
  pointers or records, block-scope helper prototypes, conditional
  function-pointer initcode initializers, no-op
  declarations/statements, file-scope scalar and struct storage variables,
  block-scope static local storage, storage/environment builtins including
  block/gas/account query opcodes, LOG0-LOG4 word and raw memory-range logs,
  Keccak memory hashing, contract
  creation and deterministic creation, self-destruction, external
  message/static/delegate/call-code calls, raw calldata, return data, runtime
  code size/copy, byte extraction, raw memory load/store, single-byte memory
  writes, active memory size, memory copy, sign extension, transient storage,
  blob hash/basefee queries, program-counter queries, and external account
  code copy opcodes, raw return/revert/stop/invalid termination opcodes,
  `PUSH0` zero constants, deployment initcode generation with aggregate,
  function-pointer, and char-array string storage initializers, and
  `__evm_uint256`/`__evm_address` ABI scalar types
- `-S`: write target assembly; for `llvm`, this is textual LLVM IR
- `-c`: write an object file, except `evm` where it writes `.bin` hex runtime
  bytecode; add `--evm-initcode` with `--target=evm -c` to write deployable
  `.init.bin` creation bytecode

On x86_64 Linux hosts, the driver defaults to `x86_64-linux-gnu`; otherwise it
defaults to `llvm`.

For the LLVM target, XCC looks for `llc` through `XCC_LLC`, `LLVM_CONFIG`, and
`PATH`. A candidate is accepted only after `llc --help` prints the LLVM `llc`
help text on stdout, so an unrelated same-name program is not used
accidentally.

## Status

- CPython: all three targets are verified at `CC="xcc" ./configure && make`
  scale, without CPython-specific compiler fallback paths
- Frontend: preprocesses, parses, and analyzes real C translation units plus
  the CPython-relevant GNU extensions encountered in system headers
- Targets: LLVM IR, native Darwin AArch64, and native x86_64 Linux all have
  working object/link driver paths; EVM has direct `.evmasm` and `.bin`
  freestanding contract bytecode outputs
- Platform: macOS ARM64 and x86_64 Linux; optional CPython extension modules
  still depend on the local system libraries available to the build

## Commands

- Install: `uv sync --dev`
- CPython build: `CC="xcc" ./configure && make`
- CPython with explicit target:
  `CC="xcc --target=aarch64-apple-darwin" ./configure && make`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Test: `uv run python -m unittest discover -v`

## Performance Benchmark

Cython and mypyc are optional benchmark tooling, not XCC runtime dependencies.
The unified benchmark runs XCC frontend compilation on a default CPython sample:
`Objects/listobject.c`, `Objects/dictobject.c`, `Python/compile.c`,
`Parser/parser.c`, and `Modules/_json.c`.

Run the interpreter matrix through tox-uv:

```
uv run tox -e bench-py311,bench-py312,bench-py313,bench-py314,bench-pypy311,bench-graalpy311,bench-graalpy312,bench-cython,bench-mypyc -- --cpython /path/to/cpython --runs 3 --warmups 1
```

The `bench-cython` and `bench-mypyc` environments run on CPython 3.11. Use
`-- --skip-build` to reuse existing compiled import trees, or run one variant
directly:

```
uv run python scripts/benchmark_xcc.py --variant all --cpython /path/to/cpython --runs 3 --warmups 1
```

Use `--profile preprocessor` for the smaller mypyc subset, or the default
`--profile frontend` for lexer plus preprocessor acceleration.

## Rules

- Standard library only at runtime
- No GPL-derived code or tests
