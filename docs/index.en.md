# Compiler Construction Guide

XCC is a C11 compiler written in Python with zero runtime dependencies. It generates LLVM IR via libLLVM-C (ctypes) and delegates to llc + clang for machine code.

This guide systematically explains the complete compiler construction process by comparing **GCC**, **Clang**, **TCC**, **CCC (Claude's C Compiler)**, and **XCC**.

## What You'll Learn

- The full pipeline from `.c` to executable
- Frontend three-stage pipeline: Preprocessor → Lexer → Parser
- Semantic analysis: type checking and symbol table management
- **The critical role of IR**: LLVM IR, MLIR/ClangIR, GCC GIMPLE/RTL, CCC custom SSA IR, TCC's no-IR approach
- Optimization pass design
- How backends translate IR to machine code

## Project Overview

| Project | Language | IR Strategy | Backend | Goal |
|---------|----------|-------------|---------|------|
| **GCC** | C/C++ | GENERIC → GIMPLE → RTL | Custom 50+ architectures | Industrial-grade, largest ecosystem |
| **Clang** | C++ | Clang AST → LLVM IR | LLVM multi-arch | Modular toolchain ecosystem |
| **TCC** | C | **No explicit IR** (value stack) | Custom x86/ARM/RISC-V | Ultimate compilation speed |
| **CCC** | Rust | Custom SSA IR + mem2reg | Custom 4 arch + assembler/linker | Fully self-contained, zero deps |
| **XCC** | Python | AST-as-IR → LLVM IR | LLVM (llc + clang) | Educational, CPython self-hosting |

## Suggested Reading Order

1. [Pipeline Overview](pipeline-overview.md) — The big picture
2. [Frontend](frontend.md) — Preprocessor, lexer, parser
3. [Semantic Analysis](semantic-analysis.md) — Type checking and symbol tables
4. [IR Landscape](ir-landscape.md) — Five IR design philosophies *(core page)*
5. [Optimization](optimization.md) — Pass design
6. [Backend & Code Generation](backend.md) — From IR to machine code
7. [Compiler Comparison](compiler-comparison.md) — Side-by-side comparison
8. [XCC Architecture](xcc-architecture.md) — Deep dive into this project
9. [Learning Path](learning-path.md) — Recommended books and projects

## Quick Start

```
uv run mkdocs serve       # Local preview
uv run mkdocs build       # Build static site
```
