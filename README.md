# XCC - An Agent-Controlled C Compiler

[![CI](https://github.com/tcztzy/xcc/actions/workflows/ci.yml/badge.svg)](https://github.com/tcztzy/xcc/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/tcztzy/xcc/actions/workflows/pages.yml/badge.svg)](https://github.com/tcztzy/xcc/actions/workflows/pages.yml)
[Project site](https://tcztzy.github.io/xcc/)

XCC is a Python 3.11+ standard-library C11 compiler and, more importantly, an
engineering specimen for keeping coding agents inside intended behavior with
specs, tests, oracles, and negative boundaries. It can act as a real `CC`
driver: CPython builds with `CC="xcc" ./configure && make` on the supported
targets.

The compiler matters, but the engineering model is the main point. XCC is built
to answer a harder question than "can an agent write code?": can a repository be
structured so agents make the changes you intend, avoid the changes you did not
intend, and leave behind evidence that the result is real?

This repo treats agent work as an engineering control problem:

- desired behavior is written down as specs and invariants, not loose prompts
- every compiler claim is tied to a reproducible command, oracle, or real build
- CPython-scale validation is allowed, but CPython-specific compiler hacks are
  forbidden
- unsupported inputs must be rejected as deliberately as supported inputs are
  accepted
- status and lessons are recorded in `CHANGELOG.md` and `LESSONS.md`, so future
  agents inherit constraints instead of rediscovering old failures

In short: XCC is a compact C compiler whose development process is designed to
keep autonomous agents inside the rails.

## Why XCC Is Different

Many agent-built projects demonstrate throughput. XCC emphasizes control. The
project is organized so an agent can move quickly, but only through narrow
interfaces that make wrong work visible:

- `SPEC.md` and `specs/` define the compiler contract as goals, constraints,
  interfaces, invariants, tasks, and bug backprops.
- `AGENTS.md` gives non-negotiable execution rules: stdlib-only runtime,
  CPython 3.11+, no GPL sources or tests, no `from __future__ import
  annotations`, and mandatory lint/type gates before handoff.
- Regression tests start from minimized C or CLI reproducers, then use clang,
  LLVM `llc`, execution results, diagnostics, or real build behavior as the
  oracle.
- `scripts/validate_compiler.py` runs differential executable checks against
  `clang` and negative boundary checks for cases XCC must not accept.
- The driver and specs explicitly ban hidden fallback backends and
  CPython-path/file special cases. Passing CPython must come from general C
  semantics.

This is the project's central bet: agent reliability comes less from asking
nicely and more from surrounding the agent with executable contracts, narrow
ledgers, deterministic tests, and explicit rejection boundaries.

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

## Agent-Control Engineering

XCC borrows the public lesson from large agent compiler projects: agents can
produce a lot of code, but the surrounding harness decides whether that code
converges on the right system. XCC makes that harness part of the repository.

The control loop is deliberately concrete:

1. Write the rule where future agents will look: `AGENTS.md` for operating
   constraints, `SPEC.md`/`specs/` for behavior contracts, `CHANGELOG.md` for
   status, and `LESSONS.md` for reusable failures.
2. Turn each bug into a small C or CLI reproducer before changing behavior.
3. Pick an oracle: clang behavior, `llc` acceptance, executable return code,
   deterministic diagnostic text, or a real build command.
4. Verify both sides of the boundary: valid programs should compile and run;
   invalid or unsupported inputs should fail clearly.
5. Run the handoff gates: `uv run tox -e py311`, `uv run tox -e lint`,
   and `uv run tox -e type`.

That loop is how the project keeps agents from "helpfully" doing the wrong
thing. A patch that passes a toy example but adds a CPython-specific shortcut,
runtime dependency, hidden fallback compiler, vague diagnostic, or unrecorded
behavior change is not progress here.

## Commands

- Install tox tooling: `uv sync --dev`
- Optional dependency groups: `test`, `lint`, `type`, `mypyc`, `cython`,
  `docs`, and `pre-commit`; tox selects only the groups required by each gate.
- CPython build: `CC="xcc" ./configure && make`
- CPython with explicit target:
  `CC="xcc --target=aarch64-apple-darwin" ./configure && make`
- CPython build validation:
  `uv run tox -e cpython-build -- /path/to/cpython`
  This gate rebuilds the mypyc import tree first and then uses it through
  `PYTHONPATH` while CPython runs `CC=xcc`.
- Native AOT profiling, DWARF debugging, Linux `perf`, and phase timing:
  [`docs/aot-native-profiling.md`](docs/aot-native-profiling.md)
- Validation: `uv run python scripts/validate_compiler.py`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Test: `uv run tox -e py311`
- Test with fixed worker count: `XCC_TEST_JOBS=1 uv run tox -e py311`
- Coverage report: `uv run --group test python scripts/run_tests.py --coverage`
- mypyc import-tree test: `uv run tox -e mypyc`

## Performance Benchmark

Cython and mypyc are optional benchmark tooling, not XCC runtime dependencies.
The unified benchmark runs XCC frontend compilation on a default CPython sample:
`Objects/listobject.c`, `Objects/dictobject.c`, `Python/compile.c`,
`Parser/parser.c`, and `Modules/_json.c`.

Frontend benchmarks are not full-project validation. Use
`uv run tox -e cpython-build -- /path/to/cpython` when the claim is that XCC can
serve as `CC` for a real CPython `configure && make` build; that gate is
mypyc-accelerated and separate from single-file timing loops.

Run the interpreter matrix through tox-uv:

```
uv run tox -e bench-py311,bench-py312,bench-py313,bench-py314,bench-pypy311,bench-graalpy311,bench-graalpy312,bench-cython,bench-mypyc -- --cpython /path/to/cpython --runs 3 --warmups 1
```

The `bench-cython` and `bench-mypyc` environments run on CPython 3.11. Use
`-- --skip-build` to reuse existing compiled import trees, or run one variant
directly:

```
uv run --group cython --group mypyc python scripts/benchmark_xcc.py --variant all --cpython /path/to/cpython --runs 3 --warmups 1
```

Use `--profile preprocessor` for the smaller mypyc subset, or the default
`--profile frontend` for lexer plus preprocessor acceleration.

## Rules

- Standard library only at runtime
- No GPL-derived code or tests
