# Learning Path

How to progressively master compiler construction, starting from basic CS knowledge.

## Stage 1: Understand the Basic Flow

**Goal**: Explain the `.c → executable` process.

**Resources**:
1. Read the [Pipeline Overview](pipeline-overview.md) in this guide
2. [Crafting Interpreters](https://craftinginterpreters.com/) (free online book)
   - Read the first half (interpreter), understand basic lexer/parser/AST implementation
   - Written in Java/C, but Python works too
3. Hand-write an **arithmetic calculator**
   - Implement lexer (`"3 + 4 * (2 - 1)"` → tokens)
   - Implement parser (recursive descent or precedence climbing)
   - Implement evaluator (walk AST to compute result)
   - **~200 lines of code, covers all core frontend concepts**

## Stage 2: Hand-Write a Mini C Compiler

**Goal**: Compile `int main() { return 42; }` to x86-64 assembly.

**Resources**:
1. Study **TCC** source code (`~/GitHub/tinycc/tccgen.c`)
   - Especially the `expr_xxx()` function family: how expression parsing merges with code generation
   - Understand how the value stack (`vstack`) replaces explicit IR
2. Study **XCC** source code (`src/xcc/lexer.py`, `src/xcc/parser/`, `src/xcc/sema/`)
   - XCC's code is highly readable in Python
   - Start with `lexer.py`, then `parser/expressions.py`'s precedence climbing
3. Suggested project steps:
   1. Implement lexer (supports int, return, literals, `{}()`, `;`)
   2. Implement parser (supports function definitions and return statements)
   3. Implement code generation (x86-64 assembly template: `mov eax, 42; ret`)
   4. Extend to binary operations (`+ - * /`)
   5. Extend to local variables

## Stage 3: Understand IR and Optimization

**Goal**: Understand SSA form, mem2reg, basic optimization passes.

**Resources**:
1. Read the [IR Landscape](ir-landscape.md) in this guide
2. **LLVM IR hands-on**:
   ```bash
   echo 'int add(int a, int b) { return a + b; }' | \
     clang -x c -S -emit-llvm -o - -
   ```
   Read the output, understand the difference between alloca/store/load and SSA.
   ```bash
   clang -x c -S -emit-llvm -O2 -o - -  # see optimization effect
   ```

3. Study **CCC**'s IR subsystem (`~/GitHub/claudes-c-compiler/src/ir/`)
   - `lowering/`: AST → alloca-based IR
   - `mem2reg/`: alloca → SSA (dominator tree + phi insertion + renaming)
   - This is the best code example for understanding SSA construction

4. Study **CCC**'s optimization passes (`~/GitHub/claudes-c-compiler/src/passes/`)
   - `constant_fold` (simplest pass)
   - `dce` (dead code elimination)
   - `gvn` (global value numbering, harder but powerful)

5. **LLVM's Kaleidoscope Tutorial** ([online](https://llvm.org/docs/tutorial/))
   - Implement a small language from scratch in C++, including JIT
   - Full coverage: lexer → parser → IR → JIT → optimizer

## Stage 4: Dive into Backends

**Goal**: Understand register allocation, instruction selection, assembly, and linking.

**Resources**:
1. **"Engineering a Compiler"** (Keith Cooper & Linda Torczon)
   - Chapter 13: Instruction Selection (tree pattern matching)
   - Chapter 14: Register Allocation (graph coloring + linear scan)
   - Chapter 12: Instruction Scheduling

2. Read the [Backend & Code Generation](backend.md) chapter in this guide

3. Study **CCC**'s codegen and assembler:
   ```
   ~/GitHub/claudes-c-compiler/src/backend/
   ├── regalloc.rs         # Linear scan register allocation
   ├── liveness.rs         # Live interval computation
   ├── generation.rs       # IR → assembly dispatch
   └── x86/codegen/        # x86-64 SysV ABI implementation
   ```

4. Study **TCC**'s code generation:
   ```
   ~/GitHub/tinycc/x86_64-gen.c   # x86-64 codegen (~3000 lines)
   ```

## Stage 5: Read Production Compilers

**Goal**: Understand the full picture of real-world compilers.

**Resources**:
1. **Clang source** (`https://github.com/llvm/llvm-project/tree/main/clang`)
   - `lib/Lex/`: Preprocessor and Lexer
   - `lib/Parse/`: Parser (recursive descent, table-driven)
   - `lib/Sema/`: Semantic analysis (most complex)
   - `lib/CodeGen/`: Clang AST → LLVM IR

2. **GCC source** (`https://gcc.gnu.org/git.html`)
   - `gcc/c/`: C frontend
   - `gcc/tree-ssa*.cc`: GIMPLE SSA optimization passes
   - `gcc/config/`: Target architecture backends

3. **LLVM source** (`https://github.com/llvm/llvm-project/tree/main/llvm`)
   - `lib/Transforms/Scalar/`: Scalar optimization passes
   - `lib/CodeGen/`: Machine IR and register allocation

## Recommended Books

| Book | Difficulty | Best For |
|------|-----------|----------|
| [Crafting Interpreters](https://craftinginterpreters.com/) | ★★ | Stage 1: Getting started |
| [Writing a C Compiler](https://norasandler.com/2017/11/29/Write-a-Compiler.html) (blog series) | ★★ | Stage 2: Implementing a C compiler |
| [LLVM Kaleidoscope Tutorial](https://llvm.org/docs/tutorial/) | ★★★ | Stage 3: LLVM IR |
| [Engineering a Compiler](https://www.elsevier.com/books/engineering-a-compiler/cooper/978-0-12-815412-0) | ★★★★ | Stage 4-5: Deep dive |
| [SSA-based Compiler Design](https://link.springer.com/book/10.1007/978-3-030-80515-9) | ★★★★ | Stage 3: SSA theory |
| [Advanced Compiler Design and Implementation](https://www.amazon.com/Advanced-Compiler-Design-Implementation-Muchnick/dp/1558603204) | ★★★★★ | Stage 5: Production-grade |

## Source Reading Order

If you want to read through all five compiler source trees, the suggested order is:

1. **TCC** → Simplest, 15K lines, understand single-pass compilation
2. **XCC** → Python is highly readable, understand modular design
3. **CCC** → Rust is clean and modern, understand SSA IR + optimization pipeline
4. **Clang** → Best documented industrial compiler
5. **GCC** → Most complete but hardest to enter

## Hands-On Projects

These projects increase in difficulty:

| Project | Est. LOC | Learning Focus |
|---------|----------|---------------|
| 1. Arithmetic calculator | ~200 | Lexer + Parser basics |
| 2. Mini interpreted language | ~500 | Variables, scopes, control flow |
| 3. C subset → x86 assembly | ~1500 | Code generation, stack frames, ABI |
| 4. Custom SSA IR | ~3000 | mem2reg, phi nodes, optimization passes |
| 5. Full C compiler | ~15000 | Frontend completeness, preprocessor, linking |

---

[Back to Home](index.md)
