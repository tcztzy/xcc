# CHANGELOG

## Current

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
