# XCC

C11 compiler written in Python. Zero runtime dependencies. Generates
LLVM IR via libLLVM-C ctypes, pipes through llc + clang for machine code.

## Pipeline

```
.c → [preprocessor → lexer → parser → sema] → LLVM IR (libLLVM-C)
   → llc → .o → clang → executable
```

- `--backend=xcc`: native LLVM path, no fallback
- `--backend=auto` (default): try native path, fall back to clang on error
- `--backend=clang`: frontend validation only, delegate to clang

## Status

- Frontend: 442/442 CPython source files parse and analyze cleanly
- Backend: compiles CPython. 10/442 files fall back to clang (float literal
  edge cases, GNU asm); rest go through native LLVM path
- Platform: macOS ARM64

## Commands

- Install: `uv sync --dev`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Test: `uv run python -m unittest discover -v`

## Rules

- Standard library only at runtime
- No GPL-derived code or tests
