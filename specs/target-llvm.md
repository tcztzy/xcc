# LLVM Target Spec

## §G GOAL
The `llvm` target emits LLVM IR and lowers object output through a discovered,
verified LLVM `llc` executable.

## §C CONSTRAINTS
- `--target=llvm` selects this target explicitly.
- Non-x86_64 Linux hosts default to this target through `driver.md`.
- Object output uses a discovered LLVM `llc`; hardcoded Homebrew-only paths are
  forbidden.
- A same-name executable is accepted only after verification that it is LLVM
  `llc`.

## §I INTERFACES
- cmd: `xcc [--target=llvm] ...` → LLVM IR target.
- cmd: `xcc --target=llvm -S source.c -o source.s` → textual LLVM IR.
- cmd: `xcc --target=llvm -c source.c -o source.o` → LLVM IR lowered through
  verified `llc`.
- file: `src/xcc/codegen.py` → LLVM IR target backend via libLLVM-C ctypes.
- file: `src/xcc/llvm_api.py` → raw libLLVM-C loading/signature boundary.

## §V INVARIANTS
V9: ∀ control-flow codegen change → emitted IR passes discovered/verified LLVM `llc` for reproducer.
V10: LLVM builder position ! read from `GetInsertBlock` after recursive emit; stale assumed block ⊥.
V11: LLVM null pointer checks ! handle `None` and `0`.
V12: `LLVMPositionBuilderAtEnd` on terminated block ⊥ unless caller proves insertion-before-terminator intended.
V19: ∀ `target=llvm` object path → `llc` command includes explicit optimization/filetype args expected by driver tests.
V288: LLVM `llc` resolution ! target=llvm object/link paths discover candidates through `XCC_LLC`, `LLVM_CONFIG`, or `PATH` and accept only executables whose `--help` stdout contains LLVM `llc` markers; a single hardcoded path or unverified same-name executable ⊥.
V366: LLVM local and static aggregate scalar initializers ! zero the destination aggregate and initialize the first member; casting a scalar value to the whole record/union type ⊥.

## §T TASKS
id|status|task|cites
T3|x|implement LLVM IR backend through libLLVM-C + `llc`|V9,V288,I.file

## §B BUGS
id|date|cause|fix
B264|2026-06-04|LLVM target object lowering hardcoded Homebrew `llc` and did not verify that a found same-name executable was LLVM `llc` before compiling IR|V288
B267|2026-06-19|LLVM local aggregate declarations with scalar initializers bypassed initializer-to-address lowering, generated scalar-to-record bitcasts, and failed to zero omitted members|V366
