# Driver Target-Selection Spec

## §G GOAL
XCC chooses one explicit compilation target per driver invocation, rejects
unsupported targets before compiling source input, and never falls back to a
hidden backend.

## §C CONSTRAINTS
- Target selection uses `--target=<name>`.
- Host default is `x86_64-linux-gnu` on x86_64 Linux, otherwise `llvm`.
- Unsupported target names fail before compiling source input.
- Runtime implementation remains Python standard library only.
- Target backends implement generic C semantics; CPython path/file/project
  identity branches are forbidden.
- A target may delegate assembling/linking to the platform toolchain, but the
  frontend and backend path must stay target-owned and visible in driver tests.

## §I INTERFACES
- cmd: `xcc [--target=<name>] ...` → CC-style compile/link driver.
- cmd: `xcc -c source.c -o source.o` → selected target object path.
- cmd: `xcc --target=evm --evm-initcode -c source.c` → EVM target writes
  deployment initcode instead of runtime bytecode.
- file: `src/xcc/cc_driver.py` → target selection and assembler/linker delegation.
- spec: `specs/target-llvm.md` → LLVM target contract.
- spec: `specs/target-aarch64-apple-darwin.md` → Darwin AArch64 target contract.
- spec: `specs/target-x86_64-linux-gnu.md` → Linux x86_64 target contract.
- spec: `specs/target-evm.md` → Ethereum Virtual Machine bytecode target
  contract.

## §V INVARIANTS
V13: `--backend` and `--no-backend-fallback` CLI options ⊥.
V14: `--target` accepted values ! explicit; unsupported target exits nonzero before compile.
V21: Broad CPython build run ! delete stale `.o` first when object cache can mask regression.
V289: Driver language standard flags ! CC-driver `-std=<mode>` controls preprocessing, parsing, and sema through `FrontendOptions.std`; accepting `-std=c11` while compiling in GNU mode ⊥.
V290: Driver generated-output actions ! `-S`/`-c` with multiple C inputs either derive one default output per input or reject explicit `-o`; overwriting one output with the last generated file ⊥.
V351: Driver EVM initcode action ! `--evm-initcode` is accepted only with
`--target=evm -c` and routes generated output through the EVM deployment
initcode generator.

## §T TASKS
id|status|task|cites
T4|x|replace backend modes with target selection defaulting to `llvm`|V13,V14,I.cmd
T18|.|verify full target `CC="xcc" ./configure && make` after high-risk codegen/sema changes|§G,V21
T79|x|add target-owned `--evm-initcode` compile output path|V351

## §B BUGS
id|date|cause|fix
B265|2026-06-04|CC-driver `-std=c11` was parsed and forwarded to the delegated tool argv but the frontend always received `std="gnu11"`, so C11 driver invocations accepted GNU-only frontend syntax|V289
B266|2026-06-04|CC-driver `-S`/`-c` computed one output path from the first C input and reused it for every input, so multi-source generated-output commands overwrote earlier outputs instead of rejecting explicit `-o` or deriving per-input defaults|V290
