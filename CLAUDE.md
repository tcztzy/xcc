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

`cd ~/GitHub/cpython && CC="xcc" ./configure && make`

## Lessons from the CPython build fix loop (2026-05)

After ~20 rounds of fixing codegen bugs for the CPython build—getting from
219 compilation errors down to 0—here is what to repeat and what to avoid.

### Builder state: read before you write

LLVM's `Builder` is mutable global state. After any call into a recursive
`_emit_expr` (which may create nested blocks in `_ternary`, `_logical`,
`_emit_case`, etc.), the builder is wherever the nested expression left it.
**Always** call `GetInsertBlock(builder)` to find out where you are before
adding terminators or instructions that assume a specific block.

```python
# Correct pattern (used in _ternary, _emit_case, _emit_default):
current_bb = c.GetInsertBlock(self._builder)
if current_bb and self._bb_needs_term(current_bb):
    c.BuildBr(self._builder, merge_bb)
```

### Don't try to reposition the builder back to the "original" block

`LLVMPositionBuilderAtEnd` on a block that already has a terminator inserts
**before** the existing terminator—producing a second terminator and
malformed IR. Nested control flow (inner `BuildCondBr` from a nested ternary
or if/else) already terminates outer blocks. You don't need to re-terminate
them. Use the builder's actual position via `GetInsertBlock`.

### Don't hand-roll state tracking the API already provides

For case fallthrough in switch: LLVM's builder position *is* the previous
case block (if it wasn't terminated by a break). `GetInsertBlock` before
emitting the next case tells you whether the previous case needs a
fallthrough branch. No need for `_prev_case_bb` manual tracking.

### Build missing features before working around them

Missing features like aggregate initializers, `static` linkage, `goto`/`label`,
`va_arg`, and enum constant lookup create cascading errors that look
unrelated. Fixing the feature gap is faster than patching around it.

### Test cycle: single-file first, then bulk

- Change code → compile **one** failing `.c` file → check IR with `llc` → iterate.
- Only run `make -k -j4` after the single-file fix works.
- **Delete `.o` files before each full build** (`find . -name '*.o' -delete`),
  otherwise make skips files with cached `.o` and masks regressions.

### Stop condition: two failures of the same pattern = wrong premise

When the same fix pattern (`_bb_needs_term` + `PositionBuilderAtEnd` +
`BuildBr`) failed identically on `_emit_case`, `_emit_default`, `_ternary`,
and `_logical`, the premise ("reposition to original block and add
terminator") was wrong—not the implementation. After the second identical
failure, question the premise, not the details.

### ctypes quirks

- ctypes maps C `NULL` pointers to Python `None`. `None == 0` is `False` in
  Python. Always check `is None or == 0` when testing for null LLVM values.
- `LLVMPositionBuilderAtEnd` with empty block → positions at start.
  With non-empty unterminated block → positions after last instruction.
  With terminated block → positions **before** the terminator (dangerous).
