# XCC — Python C11 Compiler

Target: produce a C compiler in Python that compiles CPython to a working
binary via LLVM IR.

## Pipeline

```
source.c → [preprocessor] → [lexer] → [parser] → [sema] → [llvm_codegen] → .ll
         → llc -filetype=obj → .o → clang → executable
```

- `src/xcc/codegen.py` — LLVM IR emission via libLLVM-C ctypes
- `src/xcc/cc_driver.py` — CC-style driver, invokes llc/clang for obj/link
- All frontend modules (preprocessor, lexer, parser, sema) unchanged

## Build + test

- `uv run python -m unittest discover -v` — run all tests
- `uv run tox -e lint` — ruff check
- `uv run tox -e type` — ty check
- `llc --version` — LLVM 22.1.5 expected at /opt/homebrew/opt/llvm/bin/llc

## Target

`cd ~/GitHub/cpython && CC="xcc --backend=xcc" ./configure && make`
