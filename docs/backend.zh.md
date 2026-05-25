# 后端与代码生成

后端是编译器的最后阶段：将 IR（或 AST）翻译为 CPU 可以执行的机器码。这部分是**架构相关**的——不同 CPU 需要不同的后端。

## 代码生成的三个层次

### Level 1: 委托 (Delegation)

不自己生成机器码，而是生成另一种编译器的输入，委托它完成：

| 项目 | 委托给 |
|------|--------|
| **XCC** | 生成 LLVM IR → llc → 汇编/.o → clang 链接 |
| **(某些新语言编译器)** | 生成 C 代码 → GCC/Clang 编译 |

优势：极低的实现成本。劣势：依赖外部工具链。

### Level 2: 生成汇编文本

IR → 汇编文本 → 外部汇编器 (as / gas) → .o

| 项目 | 汇编器 |
|------|--------|
| **GCC** | GAS (GNU Assembler) |
| **Clang** | 集成汇编器 (IAS) 或外部 as |

### Level 3: 直接生成机器码

IR → 机器码字节 → .o 文件，完全绕过外部汇编器。

| 项目 | 实现 |
|------|------|
| **CCC** | 自研汇编器 + ELF writer（四个架构） |
| **TCC** | `tccgen.c` 直接 emit x86/ARM/RISC-V 机器码 |

## CCC 的后端架构

CCC 是五个项目中**后端最完整的**——自建代码生成器、寄存器分配器、汇编器、链接器，全部用 Rust 从零实现。

### 架构抽象

CCC 的核心抽象是 **`ArchCodegen` trait**（~185 个方法）：

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
    // ... 共 ~185 个方法
}
```

每个架构实现这个 trait：

```
ArchCodegen trait
├── X86_64Codegen     (SysV AMD64 ABI)
├── I686Codegen       (cdecl, ILP32)
├── Aarch64Codegen    (AAPCS64)
└── RiscV64Codegen    (LP64D)
```

### 寄存器分配

CCC 使用**线性扫描寄存器分配 (Linear Scan Register Allocation)**，在所有四个后端的共享实现 (`regalloc.rs`)：

1. **活性分析 (Liveness Analysis)**：计算每个 SSA 虚拟寄存器的存活区间
2. **分配 (Register Assignment)**：线性扫描存活区间，将虚拟寄存器映射到物理寄存器
3. **溢出 (Spilling)**：当物理寄存器不够时，将值暂时存回栈槽

```
算法伪代码：
for interval in sorted(live_intervals):
    清理已过期的活跃区间，释放对应物理寄存器
    if 有空闲物理寄存器:
        分配
    else:
        选择最晚结束的活跃区间溢出到栈
```

### 函数调用 ABI

不同架构 / 操作系统有不同的调用约定：

```
x86-64 Linux (SysV AMD64 ABI):
  前 6 个整数参数：rdi, rsi, rdx, rcx, r8, r9
  前 8 个浮点参数：xmm0-xmm7
  返回值：rax (整数) / xmm0 (浮点)
  调用者保存：rax, rcx, rdx, rsi, rdi, r8-r11, xmm0-xmm15
  被调用者保存：rbx, rbp, r12-r15

AArch64 (AAPCS64):
  前 8 个整数参数：x0-x7
  前 8 个浮点参数：v0-v7
  返回值：x0 / v0
```

CCC 的 `call_abi.rs` 提供了一个统一的 ABI 分类框架，各架构后端只提供架构特定的寄存器列表。

### CCC 的内置汇编器

CCC 的汇编器遵循三阶段流水线：

```
汇编文本 (AT&T / ARM / RISC-V 语法)
    ↓ Parser
Vec<AsmStatement> (指令 + 标签 + 伪指令)
    ↓ Encoder
Vec<u8> (机器码字节 + 重定位入口)
    ↓ ELF Writer
ELF 目标文件 (.o)
```

四个架构的汇编器都从零实现：

| 架构 | 语法 | 编码特点 |
|------|------|----------|
| x86-64 | AT&T | REX 前缀, ModR/M, SIB 字节 |
| i686 | AT&T（复用 x86 parser） | 32 位操作数，无 REX |
| AArch64 | ARM 语法 | 固定 32 位编码 |
| RISC-V | RV 语法 | 固定 32 位编码，支持 RV64C 压缩 |

## TCC 的代码生成

TCC 的代码生成是**直接嵌入在语法解析中的**——`tccgen.c` 一边解析一边 emit。

### TCC 后端文件映射

| 架构 | 代码生成 | 汇编 | 链接 |
|------|----------|------|------|
| x86-64 | `x86_64-gen.c` | `x86_64-asm.c` | `x86_64-link.c` |
| i386 | `i386-gen.c` | `i386-asm.c` | `i386-link.c` |
| ARM | `arm-gen.c` | `arm-asm.c` | `arm-link.c` |
| ARM64 | `arm64-gen.c` | `arm64-asm.c` | `arm64-link.c` |
| RISC-V 64 | `riscv64-gen.c` | `riscv64-asm.c` | `riscv64-link.c` |

### 单遍代码生成的特点

TCC 不能像 GCC 那样"先收集信息，再统一生成"。它必须在第一次看到代码时就做出决策。这是**速度**的代价。

```c
// TCC 在解析到这个函数末尾时，必须在第一次看到 return 时就生成 ret 指令
// 而不是先看完整个函数再回去优化
int abs(int x) {
    if (x < 0) return -x;   // 生成: neg eax; ret
    return x;               // 生成: ret
}
// TCC 可能生成 jmp + ret 而不是一个完美的跳转结构
```

### TCC 的 `gfunc_return()`

TCC 的函数返回生成（简化逻辑）：

```c
static void gfunc_return(CType *func_type) {
    int size, r;
    CType type;
    // 从值栈中取出返回值
    vpush(&type);  // push 返回值
    // 根据类型和架构选择合适的寄存器
    r = gv(RC_INT);  // get value → 寄存器
    // 生成跳转到清理代码
    gjmp_addr(sym->cleanup_addr);
}
```

## XCC 的代码生成

XCC 不自己生成机器码。它通过 libLLVM-C 的 ctypes 绑定**程序化构建 LLVM IR**。原始 LLVM-C 加载和函数签名在 `llvm_api.py` 中，`codegen.py` 保留 AST 到 IR 的降低逻辑：

### 类型映射

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
    # ...
```

### 表达式代码生成

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

### 控制流

XCC 需要手动管理 LLVM 的基本块和分支：

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

### IR → 机器码

生成 LLVM IR 字符串后，XCC 调用外部工具链：

```
LLVM IR (字符串) → llc -filetype=obj → .o → clang (链接) → 可执行文件
```

---

## 链接

链接是将 `.o` 文件组合成最终可执行文件的过程：

### 链接的职责

1. **符号解析**：找到每个未定义符号的定义（可能在别的 .o 或库中）
2. **重定位**：修正代码中的地址引用（因为最终地址只有在链接时才确定）
3. **段布局**：决定 .text / .data / .bss 等在虚拟内存中的位置

### 各项目的链接方式

| 项目 | 链接器 | 特点 |
|------|--------|------|
| **GCC** | `collect2` + GNU `ld` | `collect2` 处理构造函数表等特殊需求 |
| **Clang** | `lld` 或系统 `ld` | `lld` 是 LLVM 生态的快速链接器 |
| **TCC** | 自研 binder | 超快的 ELF/PE/Mach-O 链接 |
| **CCC** | 自研 linker | 处理符号解析、PLT/GOT、TLS、重定位 |
| **XCC** | `clang` (委托) | 不自己实现链接 |

---

## 后端复杂性一览

| 任务 | 难度 | 需要 |
|------|------|------|
| IR → 汇编翻译 | ★★ | 理解目标 ISA（指令集架构） |
| 寄存器分配 | ★★★★ | 活性分析 + 线性扫描 / 图着色 |
| 指令选择 | ★★★ | 模式匹配 IR 到 CPU 指令 |
| 指令调度 | ★★★★ | 理解 CPU 流水线、延迟、并行度 |
| 汇编器实现 | ★★★ | 指令编码、ELF 格式 |
| 链接器实现 | ★★★★ | 符号解析、重定位、动态链接 |

---

下一站：[五编译器横向对比](compiler-comparison.md) — 一张表看清五个项目的所有维度。
