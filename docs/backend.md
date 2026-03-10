# Back End

## Preview design

- The preview backend does not introduce a general IR.
- Native code generation lowers directly from the typed/sema AST to AArch64 assembly for macOS `arm64`.
- Unsupported constructs fail with stable `codegen` diagnostics in the `XCC-CG-*` family.

## Native code generation

- Supported preview subset is intentionally narrow: scalar locals and parameters, file-scope scalar globals, literals, identifier references, scalar unary and binary operators, assignments, blocks, `return`, `if`/`else`, loops, and direct calls with scalar arguments and returns.
- The backend emits assembly only. `clang` performs assembly, object creation, and final linking.
- `--backend=xcc` is strict. `--backend=auto` falls back to `clang` when native code generation is unsupported.

## Not shipped yet

- Standalone Mach-O object emission.
- Native Linux/ELF code generation.
- A general optimization pipeline or backend IR.

## Debuggability

- Backend failures report a `codegen` diagnostic with a stable `XCC-CG-*` code.
- Frontend validation always runs before backend selection.
