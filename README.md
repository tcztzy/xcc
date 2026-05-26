# XCC

C11 compiler written in Python. Zero runtime dependencies. Generates
LLVM IR via libLLVM-C ctypes by default, treats LLVM IR as one target assembly
language, and can also emit native Darwin AArch64 assembly directly.

## Pipeline

```
.c → [preprocessor → lexer → parser → sema] → target assembly
   → assembler/linker when object or executable output is requested
```

- `--target=llvm` (default): emit LLVM IR and lower objects through llc
- `--target=aarch64-apple-darwin`: emit native Darwin AArch64 assembly
- `-S`: write target assembly; for `llvm`, this is textual LLVM IR
- `-c`: write an object file

## Status

- Frontend: parses and analyzes real C translation units without CPython-specific paths
- Target: LLVM remains the default; Darwin AArch64 has a direct assembly path for
  scalar integer leaf functions
- Platform: macOS ARM64

## Commands

- Install: `uv sync --dev`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Test: `uv run python -m unittest discover -v`

## Rules

- Standard library only at runtime
- No GPL-derived code or tests
