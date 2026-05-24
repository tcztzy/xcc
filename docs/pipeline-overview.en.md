# Compiler Pipeline Overview

All C compilers follow the same fundamental pipeline structure, but each makes different design trade-offs. This chapter establishes the global perspective.

## Universal Pipeline

```
C Source Files (.c, .h)
     │
     ▼
┌─────────────┐
│ Preprocessor │  Macro expansion, #include, conditional compilation
└─────────────┘
     │   Preprocessed C text
     ▼
┌─────────────┐
│    Lexer     │  Text → Token stream
└─────────────┘
     │   Token sequence
     ▼
┌─────────────┐
│   Parser     │  Tokens → AST
└─────────────┘
     │   AST (Abstract Syntax Tree)
     ▼
┌─────────────┐
│   Semantic   │  Type checking, symbol tables, constant evaluation
│   Analysis   │
└─────────────┘
     │   Type-annotated AST
     ▼
┌─────────────┐
│ Intermediate │  AST → lower-level representation (SSA / 3-address code / value stack)
│     IR       │
└─────────────┘
     │   IR module
     ▼
┌─────────────┐
│ Optimization │  Dead code elimination, inlining, constant folding, etc.
│  (optional)  │
└─────────────┘
     │   Optimized IR
     ▼
┌─────────────┐
│    Code      │  IR → assembly / machine code
│  Generation  │
└─────────────┘
     │   Assembly / object file
     ▼
┌─────────────┐
│  Assembler / │  Object files + libraries → executable
│   Linker     │
└─────────────┘
     │
     ▼
  Executable (ELF / Mach-O / PE)
```

## Pipeline Comparison

### GCC

```
.c → [cpp] → GENERIC trees → GIMPLE(SSA) → multi-round opt → RTL → asm → .o → ld → executable
                  │                              │                │
                  └─ language-agnostic trees     └─ target-aware  └─ GNU binutils
```

GCC's unique feature: **three-tier IR**:
- **GENERIC**: Language-independent tree IR converted from frontend ASTs
- **GIMPLE**: Three-address code (`a = b + c`), SSA form for optimization
- **RTL**: Register Transfer Language, close to assembly, handles target-specific details

### Clang / LLVM

```
.c → [clang] → Clang AST → LLVM IR → opt(optimize) → llc → .o → lld/clang → executable
                     │           │           │          │
                     └─ rich AST  └─ SSA      └─ optional└─ LLVM toolchain
```

Clang's philosophy: **one IR throughout the pipeline**. Optimization, JIT, static compilation, and LTO all operate on the same representation.

ClangIR (CIR) is an emerging **higher-level IR** between Clang AST and LLVM IR, built with MLIR, preserving C/C++ semantics.

### TCC

```
.c → [cpp+lex+parse+gen] (single pass) → x86/ARM machine code → .o → ld → executable
        │                                      │
        └─ parse-and-emit simultaneously        └─ builtin binder (optional GNU ld)
```

**TCC has no explicit IR.** The parser generates machine code as it parses, managing intermediate results via a **value stack (vstack)**. The price of ultimate speed: no global optimization.

### CCC (Claude's C Compiler)

```
.c → [prep→lex→parse→sema] → alloca IR → mem2reg → SSA IR → 15 passes → non-SSA → asm → .o → ELF
                                               │         │                         │        │
                                               └─ stack  └─ GVN/LICM/inline...    └─ custom └─ custom
```

CCC's distinction: **fully self-contained** — custom assembler, linker, four architecture backends (x86-64, i686, AArch64, RISC-V 64), zero external compiler dependencies. Uses the same alloca→mem2reg→SSA approach as LLVM.

### XCC (This Project)

```
.c → [prep→lex→parse→sema] → typed AST → LLVM IR (libLLVM-C ctypes) → llc → .o → clang → executable
                                                      │                          │       │
                                                      └─ programmatic C API      └─ llc   └─ clang
```

XCC's AST **is** the IR — the code generator walks the semantically-analyzed AST directly, building LLVM IR via libLLVM-C ctypes bindings. All optimization is delegated to LLVM's toolchain.

## The Design Trade-off Space

| Axis | One Extreme | The Other |
|------|-------------|-----------|
| Compile speed | TCC (single pass, no IR) | GCC (multi-pass, multi-tier IR) |
| Code quality | CCC/GCC (15+ passes) | TCC (local peephole only) |
| Architecture portability | LLVM (unified IR, multi-backend) | TCC (hand-written per arch) |
| Dependency complexity | GCC/LLVM (massive toolchain) | TCC/CCC (near-zero external deps) |
| Learning curve | XCC (Python + AST-as-IR) | GCC (enormous internals) |

Next: [Frontend](frontend.md) — from source text to AST.
