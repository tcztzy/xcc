# XCC

C11 compiler written in Python. Zero runtime dependencies. Generates
LLVM IR via libLLVM-C ctypes, pipes through llc + clang for machine code.

## Pipeline

```
.c → [preprocessor → lexer → parser → sema] → LLVM IR (libLLVM-C)
   → llc → .o → clang → executable
```

## Gates

- `uv run tox -e lint`
- `uv run tox -e type`
- `uv run mkdocs build --strict`
