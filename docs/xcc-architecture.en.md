# XCC Architecture

XCC is a Python 3.11+ C11/GNU11 compiler whose runtime uses only the standard library. It has one shared frontend and four explicit targets; CPython, a host compiler, and fallback backends are not hidden in the compile path.

## Main compile path

```text
CLI / CC driver
       │
       ▼
preprocessor → lexer → parser → sema
                              │
                              ▼
                       FrontendResult
                              │
          ┌───────────┬───────┼───────────┐
          ▼           ▼       ▼           ▼
        LLVM       AArch64   x86-64       EVM
          │           │       │           │
         llc        assembler/linker      bytecode
```

- `frontend.py` only orchestrates preprocessing, lexing, parsing, and semantic analysis, and converts stage failures into source-located diagnostics.
- `cc_driver.py` owns arguments, target selection, products, and tool invocation. It does not repair frontend semantics or invoke a hidden fallback compiler.
- The state objects in the `preprocessor/`, `parser/`, and `sema/` package facades own mutable state. Helpers are concrete functions for one semantic concern rather than invented abstraction interfaces.
- `ast.py` is the sole C syntax-tree representation and `types.py` is the sole semantic-type representation. Both encode pointer, array, and function declarators with ordered `declarator_ops`; no parallel legacy fields remain.
- Semantic analysis does not rewrite the AST. Expression types live in `TypeMap`; layouts, symbols, and function signatures live in `SemaUnit`; backends consume only `FrontendResult`.
- `TranslationUnit.source_map` supports random node-identity lookup for semantic diagnostics; the preorder `source_locations` stream remains valid when AOT phase promotion moves objects used by debug emission.
- `data_layout.py` is the shared authority for size, alignment, and target integer models.

## Backend boundary

`codegen.py`, `aarch64_asm.py`, `x86_64_asm.py`, and `evm.py` are four non-fallback leaf backends. They share AST traversal, types, layout, and semantic results; ABI rules, registers, instructions, and product formats stay with the owning target.

The LLVM target builds IR through `llvm_api.py` and selects a verified `llc` through `llvm_tools.py`. Native AArch64, x86-64, and EVM emit their target output directly. An unsupported construct must fail for that target rather than switch targets.

These backend files are large but are not duplicate layers: each owns the complete lowering state for one target. Splitting them by line count alone would spread register, frame, and control-flow state across more files. Only genuinely target-neutral stateless behavior belongs in a shared module, as with `walk_ast_children`.

## AOT and bootstrap path

AOT is the Python-subset compiler used to compile XCC itself, not a second C frontend:

```text
Python source
  → owned Python lexer/parser (`py_lexer.py`, `py_parser.py`, `py_ast.py`)
  → subset check + binding + analysis
  → reachable slice
  → typed AOT IR (`ir.py`, `lower.py`)
  → LLVM text + native runtime
  → native compiler / bootstrap
```

`source_contract.py` owns source-set and reachability boundaries, `slice.py` retains entry-reachable code, `lower.py` maps the Python subset to AOT IR, and `llvm_text.py` plus `core_runtime.py` own the native representation and runtime. The fixed Darwin ARM64 bootstrap tool layout is an explicit artifact-boundary convention, not compatibility logic in the general driver.

## Test boundary

Tests follow observable contracts:

1. Minimal C or Python source exercises preprocessor, parser, and sema semantics.
2. Public CLI behavior and products exercise the driver and targets.
3. Execution, LLVM tools, host oracles, and real CPython builds exercise cross-stage claims.
4. Hosted/native/bootstrap comparisons exercise the AOT closure.

One semantic rule receives one exact assertion at its lowest owning stage; upper layers remain only when they add integration value. Tests do not forge AST or IR that production cannot create, inspect source shape, or preserve branches only for a coverage number. Coverage is an observation, not a reason to keep redundant tests.

## Verdict

This is a qualified modular compiler architecture: frontend stages, shared semantics, target backends, and the AOT bootstrap boundary are clear; the import-time dependency graph is acyclic; every current module is an entry point or is reached by production code, so there is no redundant module to delete.

The limits are explicit. Several target backends and AOT lowering/runtime components are large leaves, and native C backends consume AST plus `TypeMap` without a separate shared C IR. At the current target count this is simpler than adding forwarding layers for cosmetic file size. Extract another module only when a second real consumer or repeated cross-target semantic rule appears.
