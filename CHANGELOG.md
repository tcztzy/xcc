# CHANGELOG

## Current

- LLVM IR backend via libLLVM-C ctypes. Generates IR programmatically,
  pipes through llc for .o files, clang for linking.
- `--backend=auto` falls back to clang on codegen or frontend errors.
- `--backend=xcc` uses native LLVM path exclusively.
- Frontend passes 442/442 CPython files.
- Deleted: ARM64 asm codegen, Clang suite, Docker infra, harness scripts,
  Clang test fixtures, CPython stubs.
- SemaUnit extended with `record_definitions` for codegen struct layout.
- Codegen emits incomplete arrays as `[0 x T]` and indexes arrays through
  their address, avoiding `llc` memory blowups from `[4294967295 x T]`.
- CPython `CC="xcc --backend=xcc" ./configure && make -j1` now completes
  `checksharedmods`; optional `_gdbm` and `_tkinter` remain missing due to
  local dependencies, with 0 extension import failures.
- Codegen canonicalizes `bool` to `_Bool` for LLVM type selection and
  anonymous-record typedef matching, fixing CPython `pyexpat` type sizes.
- Static local references in constant initializers now resolve to the
  function-local static global instead of creating undefined externals.
