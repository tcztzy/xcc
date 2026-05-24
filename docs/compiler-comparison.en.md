# Five Compilers Side-by-Side

One table to see all key dimensions of GCC, Clang, TCC, CCC, and XCC.

## Basic Information

| Dimension | GCC | Clang | TCC | CCC | XCC |
|-----------|-----|-------|-----|-----|-----|
| **Language** | C/C++ | C++ | C | Rust | Python |
| **First Release** | 1987 | 2007 | 2002 | 2025 | 2025 |
| **License** | GPLv3+ | Apache 2.0 | LGPLv2 | CC0-1.0 | Apache 2.0 |
| **Code Size (est.)** | ~15M lines | ~5M lines | ~15K lines | ~100K lines | ~15K lines |
| **Maintainer** | GNU Project | LLVM Foundation | Fabrice Bellard + community | Anthropic (AI-generated) | Individual |

## Design Philosophy

| Dimension | GCC | Clang | TCC | CCC | XCC |
|-----------|-----|-------|-----|-----|-----|
| **Goal** | Widest platform + best optimization | Modular toolchain + great diagnostics | Ultimate compile speed | Fully self-contained, zero deps | Educational + CPython self-hosting |
| **Dependencies** | GMP, MPFR, MPC, ISL, binutils | LLVM libs, optional libc++ | No external compiler deps | Zero compiler deps | Only Python 3.11+ + LLVM-C dylib |
| **Compile Speed (rough)** | Slow (heavy optimization) | Medium | **Very fast** (~5-10x GCC) | Medium | Slow (Python + LLVM delegation) |
| **Output Code Speed** | **Very fast** | Fast | Moderate (peephole only) | Fast (15 pass pipeline) | Fast (LLVM O2 delegated) |

## Pipeline

| Stage | GCC | Clang | TCC | CCC | XCC |
|-------|-----|-------|-----|-----|-----|
| **Preprocessor** | libcpp (token stream) | `clang::Preprocessor` | `tccpp.c` (text stream) | Rust hand-written | Python hand-written |
| **Lexer** | Inside libcpp | `clang::Lexer` | Merged `tccpp.c` | Rust hand-written | `lexer.py` |
| **Parser** | Recursive descent + partial bison | Recursive descent (table-driven) | Recursive descent | Recursive descent | Recursive descent (precedence climbing) |
| **Semantic Analysis** | ~50K lines C | ~15K lines C++ | Merged gen (~9K lines) | ~3K lines Rust | ~3.5K lines Python |
| **IR** | GENERIC→GIMPLE→RTL | LLVM IR | **None** (value stack) | Custom SSA IR | AST as IR |
| **Optimization** | 300+ passes | 150-170 passes (O2) | Local peephole | 15 passes (3 groups) | Delegated to LLVM |
| **Code Generation** | expand (GIMPLE→RTL) + asm | llc (LLVM IR→MC) | Parse-and-emit | ArchCodegen trait × 4 | libLLVM-C ctypes |
| **Assembly** | GAS / inline | Integrated assembler / GAS | Builtin | Builtin (4 arch) | Delegated to llc |
| **Linking** | collect2 + GNU ld | lld / system ld | Builtin ELF/PE/Mach-O | Builtin (4 arch) | Delegated to clang |

## IR Comparison

| Feature | LLVM IR | GCC IR (GIMPLE) | TCC | CCC IR | XCC |
|---------|---------|-----------------|-----|--------|-----|
| **SSA form** | Yes | GIMPLE stage: yes | N/A | Yes | N/A |
| **Phi nodes** | Yes | Yes (virtual operands) | N/A | Yes | N/A (AST has no phi) |
| **mem2reg** | Yes | Yes | N/A | Yes | N/A |
| **Type system** | Strongly typed | Multi-level (tree→RTL) | Runtime | Dual (CType/IrType) | Python Type |
| **IR file format** | .ll / .bc | .gimple dump | N/A | No persistence | N/A |
| **Intermediate artifacts** | bitcode (.bc) supports LTO | .s (assembly text) | N/A | None | LLVM IR string |

## Backend Support

| Architecture | GCC | Clang | TCC | CCC | XCC |
|-------------|-----|-------|-----|-----|-----|
| **x86-64** | Yes | Yes | Yes | Yes | Via LLVM |
| **x86 (i386/i686)** | Yes | Yes | Yes | Yes (i686) | Via LLVM |
| **ARM (32-bit)** | Yes | Yes | Yes | No | Via LLVM |
| **AArch64 (ARM64)** | Yes | Yes | Yes | Yes | Via LLVM |
| **RISC-V (32/64)** | Yes | Yes | Yes | Yes (RV64) | Via LLVM |
| **MIPS** | Yes | Yes | No | No | Via LLVM |
| **PowerPC** | Yes | Yes | No | No | Via LLVM |
| **Total** | **50+** | **20+** | **5** | **4** | **~20** (via LLVM) |

## Ecosystem & Tooling

| Tool | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **Debugger** | GDB | LLDB | GDB | GDB (DWARF self-produced) | LLDB/lldb |
| **Static Analysis** | `-fanalyzer` | Clang Static Analyzer | None | None | None |
| **Sanitizers** | ASan, TSan, UBSan | ASan, TSan, UBSan, MSan | None | None | None (depends on clang) |
| **LTO** | Yes (fat LTO / slim LTO) | Yes (ThinLTO / FullLTO) | No | No | No (depends on LLVM) |
| **PGO** | Yes | Yes | No | No | No |
| **LSP/IDE** | gcc + clangd | clangd | None | None | clangd |
| **Build system integration** | All | All | Partial (make/cmake) | Partial (drop-in GCC) | `--backend=auto` mode |

## Signature Capabilities

| Capability | GCC | Clang | TCC | CCC | XCC |
|-----------|-----|-------|-----|-----|-----|
| **C11 support** | Complete | Complete | Basic | Most | Most |
| **C23 support** | Experimental | Most | No | No | No |
| **GNU extensions** | All | Most | Partial | Partial | Partial |
| **C++ support** | Yes (full) | Yes (full) | No | No | No |
| **Self-hosting** | Yes | Yes (compiles LLVM) | Yes | Yes (compiles Linux) | No |
| **JIT compilation** | libgccjit | LLVM OrcJIT | tcc -run | No | No |
| **Cross-compilation** | Yes (needs sysroot) | Yes (sysroot) | Yes (sysroot) | Yes (sysroot) | Yes (via llc) |

## Best Learning Scenarios

| If you want to learn... | Study | Why |
|------------------------|-------|-----|
| Industrial-grade compiler implementation | GCC | Most complete reference implementation |
| Modular compiler architecture | Clang | Clean module boundaries, rich docs |
| Single-pass compiler principles | TCC | Minimal code (~15K), straightforward logic |
| SSA IR and optimization | CCC | Clean Rust code, 15 passes easy to grasp |
| Compiler basics (in Python) | XCC | AST as IR, highly readable Python |

---

## One-Sentence Summary

| Project | One Sentence |
|---------|-------------|
| **GCC** | Industry benchmark — 300+ optimization passes, 50+ arch support, monolithic but omnipotent |
| **Clang** | Modular LLVM frontend — API-driven toolchain ecosystem, best diagnostics in the industry |
| **TCC** | Triumph of minimalism — 15K lines, compiles Linux kernel, 5-10x faster |
| **CCC** | AI-generated miracle — fully self-contained, preprocessor to linker all hand-written, four architectures |
| **XCC** | Educational Python compiler — AST as IR, delegates heavy lifting to LLVM |

---

Next: [XCC Architecture](xcc-architecture.md) — deep dive into this project's implementation details.
