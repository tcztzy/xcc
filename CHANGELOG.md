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
