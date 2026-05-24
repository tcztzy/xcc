# Roadmap

## Near-Term

- **Eliminate clang fallbacks**: `--backend=xcc` compiles all CPython files independently.
  - Current status: 442/442 files pass frontend, 432/442 pass native LLVM backend.
  - Remaining 10 files need codegen improvements.
- **More C11 features**:
  - Variadic functions (`va_list` / `va_start` / `va_end`)
  - Bit-fields
  - `_Complex` type
  - `_Atomic` qualifier

## Mid-Term

- **Linux / ELF support**: Support Linux targets through the same libLLVM-C ctypes path.
  - Currently only supports macOS ARM64 (via Homebrew LLVM).
- **Windows / PE support**: Via LLVM's COFF backend.
- **Performance**:
  - Reduce Python overhead during code generation
  - Consider rewriting hot paths in Cython or Rust

## Long-Term

- **Self-hosting**: Compile XCC with XCC (requires compiling a Python interpreter first, or porting XCC to a lower-level language)
- **LTO support**: Generate LLVM bitcode instead of textual IR, enabling link-time optimization
- **Debug info**: Generate DWARF debug information, supporting LLDB debugging

## Completed

- [x] C11 preprocessing (macros, headers, conditional compilation, pragma)
- [x] Hand-written lexer (trigraphs, line splicing)
- [x] Recursive descent parser (precedence climbing, full declarator support)
- [x] Semantic analysis (type checking, symbol tables, implicit conversions, constant evaluation)
- [x] LLVM IR code generation (libLLVM-C ctypes)
- [x] Three backend modes (xcc / auto / clang)
- [x] GNU extensions (`__attribute__`, `typeof`, statement expressions, K&R function definitions)
- [x] CPython source parsing (442/442 files pass frontend)
- [x] CPython partial compilation (432/442 files pass native backend)
