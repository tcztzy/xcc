# Backend & Code Generation

The backend is the compiler's final stage: translating IR (or AST) into machine code the CPU can execute. This part is **architecture-dependent** — different CPUs need different backends.

## Three Levels of Code Generation

### Level 1: Delegation

Don't generate machine code yourself — generate another compiler's input and delegate:

| Project | Delegates To |
|---------|-------------|
| **XCC** | Generate LLVM IR → llc → assembly/.o → clang link |
| **(Some new language compilers)** | Generate C code → GCC/Clang compile |

Pros: extremely low implementation cost. Cons: depends on external toolchain.

### Level 2: Generate Assembly Text

IR → assembly text → external assembler (as / gas) → .o

| Project | Assembler |
|---------|-----------|
| **GCC** | GAS (GNU Assembler) |
| **Clang** | Integrated Assembler (IAS) or external as |

### Level 3: Direct Machine Code Generation

IR → machine code bytes → .o file, completely bypassing the external assembler.

| Project | Implementation |
|---------|---------------|
| **CCC** | Custom assembler + ELF writer (four architectures) |
| **TCC** | `tccgen.c` directly emits x86/ARM/RISC-V machine code |

## CCC's Backend Architecture

CCC has the **most complete backend** among the five projects — custom code generator, register allocator, assembler, and linker, all implemented in Rust from scratch.

### Architecture Abstraction

CCC's core abstraction is the **`ArchCodegen` trait** (~185 methods):

```rust
trait ArchCodegen {
    fn emit_add(&mut self, dst: Reg, lhs: Reg, rhs: Reg);
    fn emit_sub(&mut self, dst: Reg, lhs: Reg, rhs: Reg);
    fn emit_mul(&mut self, dst: Reg, lhs: Reg, rhs: Reg);
    fn emit_load(&mut self, dst: Reg, addr: Reg, ty: IrType);
    fn emit_store(&mut self, val: Reg, addr: Reg, ty: IrType);
    fn emit_call(&mut self, name: &str, args: &[Reg], ret_ty: IrType) -> Reg;
    fn emit_ret(&mut self, val: Option<Reg>);
    fn emit_br(&mut self, cond: Reg, then: Label, else_: Label);
    fn emit_jmp(&mut self, target: Label);
    // ... ~185 methods total
}
```

Each architecture implements this trait:

```
ArchCodegen trait
├── X86_64Codegen     (SysV AMD64 ABI)
├── I686Codegen       (cdecl, ILP32)
├── Aarch64Codegen    (AAPCS64)
└── RiscV64Codegen    (LP64D)
```

### Register Allocation

CCC uses **Linear Scan Register Allocation** with a shared implementation (`regalloc.rs`):

1. **Liveness Analysis**: compute live intervals for each SSA virtual register
2. **Register Assignment**: linear scan across live intervals, mapping virtual to physical registers
3. **Spilling**: when physical registers run out, temporarily store values back to stack slots

```
Algorithm pseudocode:
for interval in sorted(live_intervals):
    expire active intervals that have ended, free their physical registers
    if physical register available:
        assign
    else:
        spill the interval that ends latest to stack
```

### Function Call ABI

Different architectures / OSes have different calling conventions:

```
x86-64 Linux (SysV AMD64 ABI):
  First 6 integer args: rdi, rsi, rdx, rcx, r8, r9
  First 8 float args: xmm0-xmm7
  Return: rax (integer) / xmm0 (float)
  Caller-saved: rax, rcx, rdx, rsi, rdi, r8-r11, xmm0-xmm15
  Callee-saved: rbx, rbp, r12-r15

AArch64 (AAPCS64):
  First 8 integer args: x0-x7
  First 8 float args: v0-v7
  Return: x0 / v0
```

CCC's `call_abi.rs` provides a unified ABI classification framework — each architecture backend only supplies arch-specific register lists.

### CCC's Built-in Assembler

CCC's assembler follows a three-stage pipeline:

```
Assembly text (AT&T / ARM / RISC-V syntax)
    ↓ Parser
Vec<AsmStatement> (instructions + labels + directives)
    ↓ Encoder
Vec<u8> (machine code bytes + relocation entries)
    ↓ ELF Writer
ELF object file (.o)
```

All four architectures have assemblers from scratch:

| Arch | Syntax | Encoding Characteristics |
|------|--------|------------------------|
| x86-64 | AT&T | REX prefixes, ModR/M, SIB bytes |
| i686 | AT&T (reuses x86 parser) | 32-bit operands, no REX |
| AArch64 | ARM syntax | Fixed 32-bit encoding |
| RISC-V | RV syntax | Fixed 32-bit encoding, RV64C compression |

## TCC's Code Generation

TCC's code generation is **directly embedded in syntax parsing** — `tccgen.c` emits as it parses.

### TCC Backend Files

| Arch | Code Generation | Assembly | Linking |
|------|----------------|----------|---------|
| x86-64 | `x86_64-gen.c` | `x86_64-asm.c` | `x86_64-link.c` |
| i386 | `i386-gen.c` | `i386-asm.c` | `i386-link.c` |
| ARM | `arm-gen.c` | `arm-asm.c` | `arm-link.c` |
| ARM64 | `arm64-gen.c` | `arm64-asm.c` | `arm64-link.c` |
| RISC-V 64 | `riscv64-gen.c` | `riscv64-asm.c` | `riscv64-link.c` |

### Single-Pass Code Generation Characteristics

TCC can't collect all information first and then generate — it must decide on first sight. This is the **price of speed**.

```c
int abs(int x) {
    if (x < 0) return -x;   // generates: neg eax; ret
    return x;               // generates: ret
}
// TCC may produce jmp + ret instead of a perfect branching structure
```

## XCC's Code Generation

XCC doesn't generate machine code itself. It **programmatically builds LLVM IR** via libLLVM-C ctypes bindings. Raw LLVM-C loading and signatures live in `llvm_api.py`; `codegen.py` keeps the AST-to-IR lowering logic:

### Type Mapping

```python
def _type_to_llvm(self, t: Type) -> LLVMTypeRef:
    if t.kind == TypeKind.INT:
        return {
            1: LLVMInt1Type(),
            8: LLVMInt8Type(),
            32: LLVMInt32Type(),
            64: LLVMInt64Type(),
        }[t.size_bits]
    elif t.kind == TypeKind.PTR:
        return LLVMPointerType(LLVMInt8Type(), 0)  # opaque ptr
    elif t.kind == TypeKind.ARRAY:
        elem = self._type_to_llvm(t.subtype)
        return LLVMArrayType(elem, t.array_size)
```

### Expression Code Generation

```python
def visit_binary_expr(self, node: BinaryExpr) -> LLVMValueRef:
    lhs = self.visit(node.left)
    rhs = self.visit(node.right)
    match node.op:
        case "+": return LLVMBuildAdd(self.builder, lhs, rhs, b"")
        case "-": return LLVMBuildSub(self.builder, lhs, rhs, b"")
        case "*": return LLVMBuildMul(self.builder, lhs, rhs, b"")
        case "/":
            if node.is_unsigned():
                return LLVMBuildUDiv(self.builder, lhs, rhs, b"")
            return LLVMBuildSDiv(self.builder, lhs, rhs, b"")
```

### Control Flow

XCC manually manages LLVM basic blocks and branches:

```python
def visit_if_stmt(self, node: IfStmt):
    cond = self.visit(node.condition)
    then_block = LLVMAppendBasicBlock(self.func, b"then")
    else_block = LLVMAppendBasicBlock(self.func, b"else")
    merge_block = LLVMAppendBasicBlock(self.func, b"merge")
    LLVMBuildCondBr(self.builder, cond, then_block, else_block)
    # Then branch
    LLVMPositionBuilderAtEnd(self.builder, then_block)
    self.visit(node.then_branch)
    LLVMBuildBr(self.builder, merge_block)
    # Else branch
    LLVMPositionBuilderAtEnd(self.builder, else_block)
    if node.else_branch:
        self.visit(node.else_branch)
    LLVMBuildBr(self.builder, merge_block)
    # Merge
    LLVMPositionBuilderAtEnd(self.builder, merge_block)
```

### IR → Machine Code

After generating LLVM IR text, XCC calls external toolchain:

```
LLVM IR (string) → llc -filetype=obj → .o → clang (link) → executable
```

---

## Linking

Linking combines `.o` files into a final executable:

### Linking Responsibilities

1. **Symbol resolution**: find the definition for each undefined symbol (possibly in another .o or library)
2. **Relocation**: fix up address references in code (addresses only known at link time)
3. **Section layout**: decide .text / .data / .bss placement in virtual memory

### Linker Comparison

| Project | Linker | Characteristics |
|---------|--------|-----------------|
| **GCC** | `collect2` + GNU `ld` | `collect2` handles constructor tables etc. |
| **Clang** | `lld` or system `ld` | `lld` is LLVM ecosystem's fast linker |
| **TCC** | Builtin binder | Ultra-fast ELF/PE/Mach-O linking |
| **CCC** | Builtin linker | Symbol resolution, PLT/GOT, TLS, relocations |
| **XCC** | `clang` (delegated) | No self-implemented linking |

---

## Backend Complexity Scale

| Task | Difficulty | Requires |
|------|-----------|----------|
| IR → assembly translation | ★★ | Understanding target ISA |
| Register allocation | ★★★★ | Liveness analysis + linear scan / graph coloring |
| Instruction selection | ★★★ | Pattern matching IR to CPU instructions |
| Instruction scheduling | ★★★★ | Understanding CPU pipeline, latency, parallelism |
| Assembler implementation | ★★★ | Instruction encoding, ELF format |
| Linker implementation | ★★★★ | Symbol resolution, relocation, dynamic linking |

---

Next: [Compiler Comparison](compiler-comparison.md) — all five projects side by side in a single table.
