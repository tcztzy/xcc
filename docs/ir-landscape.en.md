# IR Landscape

**Intermediate Representation (IR)** is the soul of a compiler. Sitting between the frontend (understanding the program) and the backend (generating machine code), it is the primary vehicle for optimization and analysis.

This chapter compares the IR design philosophies, representations, and core mechanisms across five compiler projects.

---

## Why IR?

Imagine no IR: every language frontend must directly write code generators for every CPU architecture. M languages × N architectures = **M × N** code generators.

With a unified IR: all frontends lower to one IR, all backends raise from one IR to machine code. You need only **M + N** translators.

```
Without IR (M × N explosion):
  C → x86        C → ARM        C → RISC-V
  Rust → x86     Rust → ARM     Rust → RISC-V
  ...

With IR (M + N linear):
  C → IR     Rust → IR     Go → IR
                ↓
    IR → x86    IR → ARM    IR → RISC-V
```

Deeper value of IR:

1. **Optimization**: IR-level optimizations (dead code elimination, constant folding, inlining) are **architecture-agnostic** — write once, benefit all architectures
2. **Analysis**: Data-flow analysis, alias analysis, escape analysis all operate at the IR level
3. **Self-hosting**: A compiler can generate its own IR and compile itself through the backend

---

## Prerequisite: SSA Form

Before diving into specific IRs, you must understand **SSA (Static Single Assignment)**.

### What is SSA

SSA's rule is deceptively simple: **each variable is assigned exactly once**.

```c
// Original C code
int x = 1;
x = x + 2;
return x;
```

```
// Non-SSA IR
%0 = 1
%0 = add %0, 2     ← %0 assigned twice, NOT SSA!
return %0

// SSA IR
%0 = 1
%1 = add %0, 2     ← each variable assigned once
return %1
```

### What About Branches? — Phi Nodes

```c
int a = 1;
if (cond) {
    a = 2;
}
return a;  // a could be 1 or 2
```

In SSA, **phi nodes** merge values from two branches:

```
entry:
  br cond, label %then, label %merge

then:
  %a_then = 2
  br label %merge

merge:
  %a = phi [1, %entry], [%a_then, %then]
  return %a
```

`phi` means: choose the value based on which predecessor block we entered from. From `%entry` take 1, from `%then` take `%a_then`.

Phi nodes are the defining feature that distinguishes SSA from non-SSA IR.

### mem2reg: Automatic SSA Construction

Manually constructing SSA for complex C code is tedious. Better approach:

1. Allocate all local variables on **stack slots (alloca)**, accessed via load/store
2. Run the **mem2reg** pass to promote eligible allocas to SSA registers

```
Step 1: alloca-based IR (memory access)
  %ptr = alloca i32
  store i32 1, ptr %ptr
  %tmp = load i32, ptr %ptr
  %result = add i32 %tmp, 2
  store i32 %result, ptr %ptr

Step 2: After mem2reg (SSA)
  %0 = add i32 1, 2
```

Both LLVM and CCC use this strategy. It's also the best path for beginners to understand SSA.

---

## 1. LLVM IR — The Universal SSA Language

### Design Philosophy

LLVM IR is a **strongly-typed, SSA-form, low-level but target-independent** IR. It's designed to be "the universal language of the compiler world."

### Three Equivalent Forms

| Form | Extension | Use |
|------|-----------|-----|
| In-memory | (C++ API) | Inside compiler, all passes operate on this |
| Bitcode | `.bc` | Compact binary, suitable for LTO and distribution |
| Assembly text | `.ll` | Human-readable, suitable for debugging and teaching |

All three are fully equivalent — freely convertible between each other.

### LLVM IR Examples

```llvm
; int add(int a, int b) { return a + b; }

define i32 @add(i32 %a, i32 %b) {
entry:
  %result = add i32 %a, %b      ; SSA: %result assigned once
  ret i32 %result
}
```

```llvm
; int sum(int n) { int s = 0; for(int i=0; i<n; i++) s+=i; return s; }

define i32 @sum(i32 %n) {
entry:
  br label %loop

loop:                             ; basic block: loop
  %s = phi i32 [0, %entry], [%s_next, %loop]   ; phi: entry=0, self-loop=%s_next
  %i = phi i32 [0, %entry], [%i_next, %loop]   ; phi: entry=0, self-loop=%i_next
  %s_next = add i32 %s, %i
  %i_next = add i32 %i, 1
  %cond = icmp slt i32 %i_next, %n
  br i1 %cond, label %loop, label %exit

exit:
  ret i32 %s_next
}
```

### LLVM Type System

| LLVM Type | Meaning | Corresponding C Type |
|-----------|---------|---------------------|
| `i1` | 1-bit integer | `_Bool` |
| `i8` | 8-bit integer | `char` |
| `i32` | 32-bit integer | `int` (32-bit platforms) |
| `i64` | 64-bit integer | `long long` |
| `float` | 32-bit float | `float` |
| `double` | 64-bit float | `double` |
| `ptr` | opaque pointer | `void*` / `int*` (LLVM 15+ opaque ptr) |
| `[N x T]` | array | `T[N]` |
| `{T1, T2, ...}` | struct | `struct { T1; T2; }` |

### Projects Using LLVM IR

- **Clang**: builds in-memory IR modules via C++ API
- **XCC**: builds IR via libLLVM-C ctypes bindings
- **Rust**: rustc also generates LLVM IR (via `llvm-ir` crate or direct C API)

---

## 2. MLIR / ClangIR — Layered IR Ecosystem

### What is MLIR

**MLIR (Multi-Level IR)** is a **meta-IR framework** within the LLVM ecosystem. It's not a single IR but a toolbox for building IRs.

The core concept is **Dialect**: each dialect defines its own operations, types, and attributes. Dialects enable **progressive lowering** through successive conversions.

```
Dialect ecosystem (partial):
┌─────────────────────────────────────┐
│  TensorFlow / linalg / ...          │ ← high-level dialects
├─────────────────────────────────────┤
│  affine / scf (structured control)  │ ← mid-level dialects
├─────────────────────────────────────┤
│  arith / math / memref              │ ← arithmetic dialects
├─────────────────────────────────────┤
│  llvm (LLVM IR as MLIR dialect)     │ ← low-level dialect
└─────────────────────────────────────┘
```

### ClangIR (CIR)

**ClangIR** is an MLIR dialect being upstreamed into the LLVM monorepo. It sits between Clang AST and LLVM IR, solving a specific pain point:

> LLVM IR loses C/C++ language semantic information.

For example, the Clang AST knows this is a `const int`, a `virtual function call`, a `try-catch`. But LLVM IR only sees a pile of alloca/load/store/call. Many optimizations that could happen before LLVM IR are lost.

ClangIR as an intermediate layer preserves:
- C/C++ type system (including const/volatile qualifiers)
- ABI information (calling conventions, struct layout)
- Exception handling semantics
- Lifetime information

```
Clang AST → ClangIR (cir dialect) → LLVM IR → optimization → Machine IR → machine code
              │
              └─ C/C++-aware optimizations here
                 e.g.: const propagation, NRVO, virtual function devirtualization
```

### Why MLIR Matters

MLIR's value lies in **letting each problem find its appropriate abstraction level**. Not all optimizations belong at LLVM IR level, and not all information should sink to LLVM IR.

- Deep learning frameworks use high-level dialects for loop fusion
- Hardware compilers use custom dialects for chip instructions
- ClangIR uses a C/C++ dialect for language-aware optimizations

---

## 3. GCC IR — Three-Tier Cascading IR

GCC has the **most IR tiers** among the five projects: GENERIC to GIMPLE to RTL, each solving optimization at a different granularity.

### 3.1 GENERIC — Unified Frontend Trees

GENERIC is a **language-independent tree IR**. Every C expression, statement, and declaration maps to a `tree` node. Its role is to provide a unified data structure so all language frontends feed into the same optimization pipeline.

```
C FE trees → GENERIC
C++ FE trees → GENERIC
Fortran FE trees → GENERIC
                  ↓
            GIMPLE (optimization)
```

In practice, C/C++ frontends don't generate full GENERIC — they jump straight to GIMPLE generation ("gimplification").

### 3.2 GIMPLE — Three-Address Code

GIMPLE is a restricted three-address code format. Converting GENERIC to GIMPLE is called "gimplification."

**Three-address code** means each instruction has at most three operands (two sources, one destination).

```c
// C code
a = b + c * d;
```

```
// GIMPLE (simplified)
t1 = c * d;       // at most two source operands per instruction
a = b + t1;       // temporaries introduced
```

GIMPLE has 5 main instruction types (called "tuples" in GCC):

| GIMPLE Code | Meaning |
|-------------|---------|
| `GIMPLE_ASSIGN` | `lhs = rhs` |
| `GIMPLE_COND` | `if (cond) goto label_1 else goto label_2` |
| `GIMPLE_CALL` | `lhs = foo(args)` |
| `GIMPLE_RETURN` | `return val` |
| `GIMPLE_SWITCH` | `switch(val)` |

GCC builds SSA on GIMPLE, then runs most optimization passes on SSA-form GIMPLE (inlining, DCE, GVN, LICM, etc.).

### 3.3 RTL — Near-Assembly Representation

RTL (Register Transfer Language) is the IR closest to the target architecture. It uses **virtual registers** (effectively infinite) for computation; mapping to physical registers is done by the register allocator.

```
RTL instruction example (target-independent):
  (set (reg:SI 100)                ; virtual register 100
       (plus:SI (reg:SI 101)       ; reg 100 = reg 101 + reg 102
                (reg:SI 102)))
```

RTL optimizations include:
- **Register allocation** (virtual → physical)
- **Instruction selection** (RTL patterns → specific CPU instructions)
- **Instruction scheduling** (reorder to avoid pipeline stalls)
- **Peephole optimization** (local instruction pattern replacement)

### Full Pipeline

```
C Source
  ↓
C FE → GENERIC trees (language-independent)
  ↓ gimplification
High GIMPLE (retains lexical scopes)
  ↓ pass_lower_cf (lower control flow)
Low GIMPLE (all implicit jumps exposed)
  ↓ build_ssa
GIMPLE SSA (phi nodes + virtual operands)
  ↓ ~300+ optimization passes
Optimized GIMPLE SSA
  ↓ expand (expand to RTL)
RTL (virtual registers + target-aware)
  ↓ register allocation + scheduling + peephole
Assembly → .o → linker
```

---

## 4. TCC — No IR, Value Stack Approach

TCC's philosophy is the polar opposite of GCC's: **compilation speed above all, no explicit IR whatsoever**.

### Value Stack

TCC generates machine code while parsing C code. Intermediate expression results are stored on a **value stack (vstack)**.

```c
// TCC's SValue structure (simplified)
typedef struct SValue {
    CType type;     // value type
    unsigned short r;    // register number (VT_CONST = constant)
    unsigned short r2;   // second register (needed for 64-bit ops)
    union {
        long long i;     // constant value
        int jtrue;       // conditional jump true target
        int jfalse;      // conditional jump false target
    };
} SValue;
```

### How the Value Stack Works

For `a + b * c`:

```
1. Parse 'a': push(SValue{type=int, r=reg_of_a})         stack: [a]
2. Parse 'b': push(SValue{type=int, r=reg_of_b})         stack: [a, b]
3. Parse 'c': push(SValue{type=int, r=reg_of_c})         stack: [a, b, c]
4. Hit '*':
   pop(b), pop(c) → gen_opi('*') → emit 'imul ecx, edx' → push(result)
                                                          stack: [a, b*c]
5. Hit '+':
   pop(a), pop(b*c) → gen_opi('+') → emit 'add eax, ecx' → push(result)
                                                          stack: [a+b*c]
```

In `tccgen.c`, parsing and code generation are interleaved. `gfunc_return()` generates ret instructions, `expr_eq()` parses and generates assignment code.

### TCC's Advantages and Limitations

**Advantages**:
- Ultimate compilation speed: TCC compiles the Linux kernel 5-10x faster than GCC
- Minimal memory: no IR data structures to maintain
- Simple code: entire compiler ~15K lines

**Limitations**:
- No cross-basic-block optimization: can't do DCE, GVN, etc.
- Lower code quality: relies on LLVM/GCC for real optimization
- Only local peephole: shift-for-multiply, constant folding within expressions
- No LTO: no IR to share across files

---

## 5. CCC — Custom SSA IR

CCC takes a middle path: building a complete custom SSA IR, but keeping it compact and educational.

### Design Decisions

CCC's IR follows LLVM's core principles but simplifies:

| Feature | LLVM | CCC |
|---------|------|-----|
| SSA construction | alloca → mem2reg | alloca → mem2reg (same strategy) |
| Phi nodes | supported | supported |
| Basic blocks | `BasicBlock` with `Instruction` list | same design |
| Type system | complete type hierarchy | dual: `CType` + `IrType` |
| Memory model | alloca + load/store + GEP | ptr + load/store (no GEP, simpler) |

### CCC IR Core Structures

```
IrFunction
├── name: String
├── params: Vec<IrReg>      // function parameters (SSA virtual registers)
├── blocks: Vec<IrBlock>    // basic block list
│   ├── label: String
│   ├── phis: Vec<(IrReg, ...)>  // phi nodes
│   └── body: Vec<IrInstr>       // instruction list
└── locals: Vec<IrReg>      // local variables (before mem2reg: alloca, after: SSA reg)
```

### IR Instructions

CCC's IR instructions are an enum with ~30 variants:

```rust
enum IrInstr {
    Add(IrReg, IrReg),          // r = a + b
    Sub(IrReg, IrReg),          // r = a - b
    Mul(IrReg, IrReg),          // r = a * b
    Icmp(Cond, IrReg, IrReg),   // r = a < b (produces i1)
    Load(IrReg),                // r = *addr
    Store(IrReg, IrReg),        // *addr = val
    Call(String, Vec<IrReg>),   // r = func(args)
    Phi(Vec<(IrReg, String)>),  // phi [val, block]
    Br(IrReg, String, String),  // if cond { goto a } else { goto b }
    Jmp(String),                // goto block
    Ret(IrReg),                 // return val
    // ... ~30 total
}
```

### Dual Type System

A unique CCC design: **separating C semantic types from machine-level types**:

- `CType`: preserves C language type semantics (`int` vs `long` distinction, `const`, `volatile`, etc.), used for **semantic analysis** type checking
- `IrType`: flat machine-level type enumeration (`I8`, `I16`, `I32`, `I64`, `U8`, ..., `F32`, `F64`, `F128`, `Ptr`, `Void`), used for **IR and code generation**

```
C code:  const unsigned short x = 42;

CType:   UnsignedShort(const=true)       → semantic analysis
IrType:  U16                             → IR and code generation
```

### CCC's mem2reg Implementation

CCC's mem2reg follows the standard algorithm:

```
1. Build CFG (Control Flow Graph)
2. Compute dominator tree
3. Compute dominance frontier → decide where to insert phi nodes
4. For each alloca:
   a. Insert phi nodes at dominance frontier
   b. Rename: walk dominator tree, replace stores/loads with SSA registers
5. Delete unused allocas
```

This is essentially the same algorithm as LLVM's mem2reg pass.

### 15 Optimization Passes

CCC has 15 SSA optimization passes organized into three groups:

**Phase 0: Inline related**
```
inline → mem2reg → constant_fold → copy_prop → simplify
  → constant_fold → copy_prop → resolve_asm
```

**Main Loop (up to 3 iterations, dirty-tracked)**
```
cfg_simplify → copy_prop → div_by_const → narrow → simplify
  → constant_fold → gvn → licm → iv_strength_reduce
  → if_convert → copy_prop → dce → cfg_simplify → ipcp
```

**Cleanup**
```
dead_statics → phi elimination (SSA → register copies)
```

Dirty tracking: if a pass makes no changes, downstream passes can be skipped.

---

## 6. XCC — AST as IR

XCC takes a route different from all others: **no IR lowering**. The type-annotated AST serves directly as the IR.

### Design Philosophy

XCC's fundamental insight: for CPython (a C project prioritizing readability, maintainability, and portability over extreme performance), maintaining a custom IR and optimization passes has very low ROI.

XCC's strategy:
1. Frontend performs precise semantic analysis and type resolution
2. Insert implicit conversion nodes (`ImplicitCast`) into the AST
3. Code generator walks this "rich AST" directly, calling libLLVM-C functions
4. All optimization delegated to LLVM's `llc` (built-in optimization pipeline)

### AST as IR — Feasibility

| What traditional IR does | How XCC's AST achieves it |
|--------------------------|---------------------------|
| Type information | AST nodes associated with `Type` during Sema |
| Constant values | constexpr results recorded in `TypeMap` |
| Control flow | `IfStmt`, `ForStmt`, `WhileStmt` AST nodes |
| Function calls | `CallExpr` nodes + `FunctionSymbol` |
| Implicit conversions | Explicitly inserted `ImplicitCast` AST nodes |

### Code Generation: AST → LLVM IR

XCC's code generator (`codegen.py`) key logic:

```python
class _LLVMGen:
    def visit_binary_expr(self, node: BinaryExpr) -> LLVMValueRef:
        left_val = self.visit(node.left)
        right_val = self.visit(node.right)
        if node.op == "+":
            return LLVMBuildAdd(self.builder, left_val, right_val, b"")
        elif node.op == "-":
            return LLVMBuildSub(self.builder, left_val, right_val, b"")

    def visit_if_stmt(self, node: IfStmt) -> None:
        cond = self.visit(node.condition)
        LLVMBuildCondBr(self.builder, cond, then_block, else_block)

    def visit_call_expr(self, node: CallExpr) -> LLVMValueRef:
        func = self.resolve_function(node.name)
        args = [self.visit(a) for a in node.args]
        return LLVMBuildCall2(self.builder, func_type, func, args, b"")
```

### Benefits and Costs

**Benefits**:
- Easy to understand: AST is a compiler developer's most familiar data structure
- Debugging-friendly: can log, breakpoint at the AST level
- Lower code volume: no need to implement SSA construction, mem2reg, phi elimination

**Costs**:
- Can't perform any IR-level optimization within XCC (delegated to llc)
- Can't do LTO (would need intermediate IR files)
- Control flow (loops, branches) requires the code generator to manually manage basic blocks and jumps

---

## Comparison Table

| Feature | LLVM IR | MLIR/ClangIR | GCC IR | TCC | CCC IR | XCC |
|---------|---------|-------------|--------|-----|--------|-----|
| **IR Tier count** | 1 (LLVM IR) | N (dialect chain) | 3 (GENERIC→GIMPLE→RTL) | 0 | 1 (SSA IR) | 0 (AST-as-IR) |
| **SSA** | Yes | Varies by dialect | GIMPLE stage: yes | N/A | Yes | N/A |
| **Type system** | Strongly typed | Varies by dialect | Multi-level (tree→RTL) | Runtime | Dual (CType/IrType) | Python `Type` |
| **Optimization location** | On IR | On each dialect | On GIMPLE+RTL | Local peephole | On IR (15 passes) | Delegated to LLVM |
| **Self-built optimization** | All | Partial | All | Peephole | 15 passes | 0 |
| **Self-built backend** | All | Partial | All (50+ arch) | x86/ARM/RISC-V | 4 arch + asm + linker | 0 (LLVM delegated) |
| **Phi nodes** | Supported | Varies by dialect | GIMPLE SSA: yes | N/A | Supported | N/A |

---

## Recommended IR Learning Path

If you're a beginner, learn IR in this order:

1. **Start with XCC**: understand what "AST as IR" means. Manually insert conversion nodes on the AST to feel why a lower-level representation is needed.

2. **Read LLVM IR `.ll` output**: use `clang -S -emit-llvm hello.c` to generate textual IR. Read a simple function's IR, understand alloca/store/load and SSA registers.

3. **Study CCC's mem2reg**: CCC's code is clean, mem2reg implementation is compact (~500 lines), making it the best textbook for understanding SSA construction.

4. **Understand GIMPLE**: use `gcc -fdump-tree-all` to export GCC's per-pass GIMPLE dumps. Watch how a simple function changes before and after optimization.

5. **Appreciate MLIR's philosophy**: you don't need to write MLIR code, but understand the idea that "different optimizations need different abstraction levels."

---

Next: [Optimization](optimization.md) — once IR is built, how the compiler makes code run faster.
