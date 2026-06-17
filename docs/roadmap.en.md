# Roadmap

## Near-Term

- **Public evidence loop**: keep CI, validation, lint, type, and Pages
  deployment gates green so XCC's agent-control claims remain reproducible.
- **Regression conversion**: turn CPython-discovered failures into generic
  minimized C or CLI reproducers with clang, `llc`, diagnostic, execution, or
  real-build oracles.
- **C11/GNU edge coverage**: continue filling remaining frontend and target
  gaps exposed by real system headers and CPython-scale builds.

## Mid-Term

- **Target matrix hardening**: keep LLVM, native Darwin AArch64, native Linux
  x86_64, and EVM outputs covered by focused smoke checks.
- **Windows / PE support**: Evaluate a Windows target through LLVM COFF output
  or a future native path.
- **Performance**:
  - Reduce Python overhead in frontend and target lowering hot paths.
  - Keep Cython and mypyc as optional benchmark variants, not runtime
    dependencies.

## Long-Term

- **Self-hosting**: Compile XCC with XCC (requires compiling a Python interpreter first, or porting XCC to a lower-level language)
- **LTO support**: Generate LLVM bitcode instead of textual IR, enabling link-time optimization
- **Debug info**: Generate DWARF debug information, supporting LLDB debugging

## Completed

- [x] C11 preprocessing (macros, headers, conditional compilation, pragma)
- [x] Hand-written lexer (trigraphs, line splicing)
- [x] Recursive descent parser (precedence climbing, full declarator support)
- [x] Semantic analysis (type checking, symbol tables, implicit conversions, constant evaluation)
- [x] LLVM IR target (libLLVM-C ctypes plus verified `llc` object lowering)
- [x] Target model with host default and explicit `llvm`, `aarch64-apple-darwin`, `x86_64-linux-gnu`, and `evm` targets
- [x] Native Darwin AArch64 and native Linux x86_64 CPython-scale build support
- [x] GNU extensions (`__attribute__`, `typeof`, statement expressions, K&R function definitions)
- [x] CPython source parsing (442/442 files pass frontend)
- [x] CPython build as flagship integration target
- [x] Agent-control documentation, validation harness, and GitHub Pages landing page
