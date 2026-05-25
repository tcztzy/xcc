# XCC

C11 compiler written in Python. Zero runtime dependencies. Generates
LLVM IR via libLLVM-C ctypes, treats LLVM IR as the default target assembly
language, and pipes through llc + clang for machine code.

## Pipeline

```
.c → [preprocessor → lexer → parser → sema] → LLVM IR (libLLVM-C)
   → llc → .o → clang → executable
```

- `--target=llvm` (default): emit LLVM IR and lower objects through llc
- `-S`: write target assembly; for `--target=llvm`, this is textual LLVM IR
- `-c`: write an object file

## Status

- Frontend: parses and analyzes real C translation units without CPython-specific paths
- Target: LLVM object/link path is the default compiler path, with no clang fallback mode
- Platform: macOS ARM64

## Commands

- Install: `uv sync --dev`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Test: `uv run python -m unittest discover -v`

## Rules

- Standard library only at runtime
- No GPL-derived code or tests
