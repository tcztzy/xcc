# IR 全景对比

**中间表示 (Intermediate Representation, IR)** 是编译器的灵魂。它位于前端（理解程序）和后端（生成机器码）之间，是优化和分析的主要载体。

本章对比五种编译器项目中 IR 方案的设计哲学、表示形式和核心机制。

---

## 为什么需要 IR

想象没有 IR 的情况：每个语言前端必须直接为每个 CPU 架构编写代码生成器。如果有 M 种语言和 N 种架构，需要 **M × N** 个代码生成器。

有了统一的 IR：所有语言前端降到同一种 IR，所有后端从同一种 IR 升到机器码。只需要 **M + N** 个转换器。

```
没有 IR (M × N 爆炸)：
  C → x86        C → ARM        C → RISC-V
  Rust → x86     Rust → ARM     Rust → RISC-V
  ...

有 IR (M + N 线性)：
  C → IR     Rust → IR     Go → IR
                ↓
    IR → x86    IR → ARM    IR → RISC-V
```

但这只是 IR 最浅层的好处。更深层的价值在于：

1. **优化**：IR 层面的优化（死代码消除、常量折叠、内联）是**架构无关的**，写一次对所有架构生效
2. **分析**：数据流分析、别名分析、逃逸分析都在 IR 层面进行
3. **自举**：编译器可以用自己生成自己的 IR，再用后端编译自己

---

## 前置概念：SSA 形式

在深入各 IR 之前，必须先理解 **SSA (Static Single Assignment)**。

### 什么是 SSA

SSA 的规则极其简单：**每个变量只被赋值一次**。

```c
// 原始 C 代码
int x = 1;
x = x + 2;
return x;
```

```
// 非 SSA IR
%0 = 1
%0 = add %0, 2     ← 对 %0 赋值两次，不是 SSA！
return %0

// SSA IR
%0 = 1
%1 = add %0, 2     ← 每个变量只赋值一次
return %1
```

### 遇到分支怎么办？—— Phi 节点

```c
int a = 1;
if (cond) {
    a = 2;
}
return a;  // a 可能是 1 也可能是 2
```

在 SSA 中，用 **phi 节点**合并两个分支的值：

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

`phi` 的含义：根据从哪个前驱基本块进入，选择对应的值。从 `%entry` 来就取 1，从 `%then` 来就取 `%a_then`。

phi 节点是 SSA IR 区别于非 SSA IR 的核心特征。

### mem2reg：自动构造 SSA

直接为复杂的 C 代码手工构造 SSA 非常繁琐。更好的方法是：

1. 先将所有局部变量分配在**栈槽 (alloca)** 上，用 load/store 访问
2. 然后运行 **mem2reg** pass，将符合条件的 alloca 提升为 SSA 寄存器

```
步骤 1: alloca-based IR (内存访问)
  %ptr = alloca i32
  store i32 1, ptr %ptr
  %tmp = load i32, ptr %ptr
  %result = add i32 %tmp, 2
  store i32 %result, ptr %ptr

步骤 2: mem2reg 后 (SSA)
  %0 = add i32 1, 2
```

LLVM 和 CCC 都使用这个策略。这也是初学者理解 SSA 的最佳路径。

---

## 1. LLVM IR — 通用 SSA 语言

### 设计理念

LLVM IR 是 **强类型、SSA 形式、低层但架构无关** 的 IR。它不是为了某一个语言或架构设计的，而是试图成为"编译器世界的通用语言"。

### 三种等价形式

| 形式 | 文件后缀 | 用途 |
|------|----------|------|
| 内存表示 | (C++ API) | 编译器内部，所有 pass 操作的对象 |
| 位码 (Bitcode) | `.bc` | 紧凑二进制，适合 LTO 和分发 |
| 汇编文本 | `.ll` | 人类可读，适合调试和教学 |

三者完全等价——可以自由互相转换。

### LLVM IR 示例

```llvm
; 一个简单的函数：int add(int a, int b) { return a + b; }

define i32 @add(i32 %a, i32 %b) {
entry:
  %result = add i32 %a, %b      ; SSA: %result 只被赋值一次
  ret i32 %result
}
```

```llvm
; 更复杂的例子：循环求和
; int sum(int n) { int s = 0; for(int i=0; i<n; i++) s+=i; return s; }

define i32 @sum(i32 %n) {
entry:
  br label %loop                  ; 无条件跳入循环

loop:                             ; 基本块: loop
  %s = phi i32 [0, %entry], [%s_next, %loop]   ; phi: 入口=0, 自循环=%s_next
  %i = phi i32 [0, %entry], [%i_next, %loop]   ; phi: 入口=0, 自循环=%i_next
  %s_next = add i32 %s, %i
  %i_next = add i32 %i, 1
  %cond = icmp slt i32 %i_next, %n
  br i1 %cond, label %loop, label %exit

exit:
  ret i32 %s_next
}
```

### LLVM 类型系统

| LLVM 类型 | 含义 | 对应 C 类型 |
|-----------|------|-------------|
| `i1` | 1 位整数 | `_Bool` |
| `i8` | 8 位整数 | `char` |
| `i32` | 32 位整数 | `int` (32位平台) |
| `i64` | 64 位整数 | `long long` |
| `float` | 32 位浮点 | `float` |
| `double` | 64 位浮点 | `double` |
| `ptr` | 不透明指针 | `void*` / `int*` (LLVM 15+ opaque ptr) |
| `[N x T]` | 数组 | `T[N]` |
| `{T1, T2, ...}` | 结构体 | `struct { T1; T2; }` |

### LLVM IR 的关键模式

**alloca + load/store**：局部变量先分配在栈上，mem2reg 后自动提升为 SSA：
```llvm
entry:
  %ptr = alloca i32          ; 在栈上分配一个 int
  store i32 42, ptr %ptr     ; 写入 42
  %val = load i32, ptr %ptr  ; 读回
  ; mem2reg 后这两条 store/load 会消失，直接用常量 42
```

**GEP (GetElementPtr)**：计算结构体/数组成员的地址，不访问内存：
```llvm
  %field_ptr = getelementptr {i32, i32}, ptr %struct_ptr, i32 0, i32 1
  ; 等价于 &struct_ptr->field_1
```

### 使用 LLVM IR 的项目

- **Clang**：通过 C++ API 直接构建内存中的 IR 模块
- **XCC**：通过 libLLVM-C 的 ctypes 绑定，程序化构建 IR 模块
- **Rust**：rustc 也生成 LLVM IR（通过 `llvm-ir` crate 或直接调用 C API）

---

## 2. MLIR / ClangIR — 分层 IR 生态

### MLIR 是什么

**MLIR (Multi-Level IR)** 是 LLVM 生态中的一个 **元 IR 框架**。它不是一种单一的 IR，而是一个构建 IR 的工具箱。

核心概念是 **Dialect（方言）**：每个 dialect 定义自己的操作 (operation)、类型 (type) 和属性 (attribute)。Dialect 之间可以**渐进降低 (progressive lowering)**。

```
方言生态系统（部分）：
┌─────────────────────────────────────┐
│  TensorFlow / linalg / ...          │ ← 高级方言
├─────────────────────────────────────┤
│  affine / scf (结构化控制流)         │ ← 中级方言
├─────────────────────────────────────┤
│  arith / math / memref              │ ← 运算方言
├─────────────────────────────────────┤
│  llvm (LLVM IR 的 MLIR 包装)        │ ← 底层方言
└─────────────────────────────────────┘
```

### ClangIR (CIR)

**ClangIR** 是一个正在上游到 LLVM monorepo 的 MLIR dialect。它位于 Clang AST 和 LLVM IR 之间，解决一个具体痛点：

> LLVM IR 丢失了 C/C++ 语言的语义信息。

举例：Clang AST 知道这是一个 `const int`，是一个 `virtual 函数调用`，是一个 `try-catch`。但 LLVM IR 只能看到一堆 alloca/load/store/call。很多可以在 LLVM IR 之前做的优化就丢失了机会。

ClangIR 作为中间层，保留了：
- C/C++ 类型系统（包括 const/volatile 等限定符）
- ABI 信息（调用约定、结构体布局）
- 异常处理语义
- 生存期信息

```
Clang AST → ClangIR (cir dialect) → LLVM IR → 优化 → Machine IR → 机器码
              │
              └─ 在这里做 C/C++ 感知的优化
                 比如：const 传播、NRVO、虚函数去虚拟化
```

### 为什么 MLIR 重要

MLIR 的价值在于 **让每个问题找到自己合适的抽象层级**。不是所有优化都适合在 LLVM IR 层面做，也不是所有信息都应该下沉到 LLVM IR。

- 深度学习框架（TensorFlow/PyTorch）用高级 dialect 做循环融合
- 硬件编译器用自定义 dialect 表示芯片指令
- ClangIR 用 C/C++ dialect 做语言感知优化

---

## 3. GCC IR — 三层级联 IR

GCC 是五个项目中 **IR 层级最多的**：从 GENERIC 到 GIMPLE 到 RTL，每种 IR 解决不同粒度的优化问题。

### 3.1 GENERIC — 统一前端树

GENERIC 是 **语言无关的树 IR**。每个 C 表达式、语句、声明都映射到 `tree` 节点。它的作用是提供了一个统一的数据结构，让所有语言前端都能接入同一个优化流水线。

```
C FE trees → GENERIC
C++ FE trees → GENERIC
Fortran FE trees → GENERIC
                  ↓
            GIMPLE (优化)
```

但实际上 C/C++ 前端并不生成完整的 GENERIC，而是直接跳到了 GIMPLE 生成阶段（"gimplification"）。

### 3.2 GIMPLE — 三地址码

GIMPLE 是一种受限的三地址码形式。从 GENERIC 到 GIMPLE 的过程叫 "gimplification"。

**三地址码** 的含义：每条指令最多有三个操作数（两个源，一个目标）。

```c
// C 代码
a = b + c * d;
```

```
// GIMPLE (简化)
t1 = c * d;       // 每条指令最多两个源操作数
a = b + t1;       // 引入临时变量
```

GIMPLE 有 5 种主要指令（在 GCC 内部叫 "tuple"）：

| GIMPLE Code | 含义 |
|-------------|------|
| `GIMPLE_ASSIGN` | `lhs = rhs` |
| `GIMPLE_COND` | `if (cond) goto label_1 else goto label_2` |
| `GIMPLE_CALL` | `lhs = foo(args)` |
| `GIMPLE_RETURN` | `return val` |
| `GIMPLE_SWITCH` | `switch(val)` |

GCC 在 GIMPLE 上构建 SSA，然后在 SSA 形式的 GIMPLE 上运行大部分优化 pass（内联、死代码消除、GVN、LICM 等）。

### 3.3 RTL — 接近汇编的表示

RTL (Register Transfer Language) 是与目标架构最接近的 IR。它使用 **虚拟寄存器**（无限多）来表示计算，与真实寄存器之间的映射由寄存器分配器完成。

```
RTL 指令示例（x86 的平台无关 RTL）：
  (set (reg:SI 100)                ; 虚拟寄存器 100
       (plus:SI (reg:SI 101)       ; reg 100 = reg 101 + reg 102
                (reg:SI 102)))
```

RTL 的优化包括：
- **寄存器分配**（虚拟 → 物理）
- **指令选择**（RTL 模式 → 具体 CPU 指令）
- **指令调度**（重排指令避免流水线停顿）
- **窥孔优化**（局部指令模式替换）

### 完整流水线

```
C 源文件
  ↓
C FE → GENERIC trees（语言无关树）
  ↓ gimplification
High GIMPLE（保留词法作用域）
  ↓ pass_lower_cf（降低控制流）
Low GIMPLE（所有隐式跳转暴露）
  ↓ build_ssa（构建 SSA）
GIMPLE SSA（phi 节点 + 虚拟操作数）
  ↓ ~300+ optimization passes
优化后的 GIMPLE SSA
  ↓ expand（展开为 RTL）
RTL（虚拟寄存器 + 目标相关）
  ↓ register allocation + scheduling + peephole
汇编 → .o → linker
```

---

## 4. TCC — 无 IR 的值栈方案

TCC 的设计哲学与 GCC 形成极端对比：**编译速度压倒一切，不要任何显式 IR**。

### 值栈 (Value Stack)

TCC 在解析 C 代码的同时生成机器码。表达式求值的中间结果存储在一个 **值栈 (vstack)** 中。

```c
// TCC 的 SValue 结构（简化）
typedef struct SValue {
    CType type;     // 值的类型
    unsigned short r;    // 寄存器编号 (VT_CONST 表示常量)
    unsigned short r2;   // 第二个寄存器（64位操作需要）
    union {
        long long i;     // 常量值
        int jtrue;       // 条件跳转的 true 目标
        int jfalse;      // 条件跳转的 false 目标
    };
} SValue;
```

### 值栈工作原理

以表达式 `a + b * c` 为例：

```
1. 解析 'a'：push(SValue{type=int, r=reg_of_a})        栈: [a]
2. 解析 'b'：push(SValue{type=int, r=reg_of_b})        栈: [a, b]
3. 解析 'c'：push(SValue{type=int, r=reg_of_c})        栈: [a, b, c]
4. 遇到 '*'：
   pop(b), pop(c) → gen_opi('*') → emit 'imul ecx, edx' → push(result)
                                                        栈: [a, b*c]
5. 解析 '+'：
   pop(a), pop(b*c) → gen_opi('+') → emit 'add eax, ecx' → push(result)
                                                        栈: [a+b*c]
```

TCC 的 `tccgen.c` 中，解析和代码生成交织在一起。`gfunc_return()` 生成 ret 指令，`expr_eq()` 解析并生成赋值代码。

### TCC 的优势与局限

**优势**：
- 极致编译速度：TCC 编译 Linux 内核比 GCC 快 5-10 倍
- 内存占用极低：不需要维护任何 IR 数据结构
- 代码简单：整个编译器 ~15000 行

**局限**：
- 无跨基本块优化：不能做死代码消除、全局值编号等
- 生成的代码质量低：依赖 LLVM/GCC 做真正优化
- 只做局部窥孔优化：如用移位替代乘法、常量折叠等
- 无法做 LTO（链接时优化）：没有可跨文件共享的 IR

### 窥孔优化示例

TCC 在代码生成时做简单的局部优化：

```c
// 窥孔：常量折叠
int x = 3 + 4;  // TCC 直接计算为 7，不生成 add 指令

// 窥孔：强度削减
int x = a * 2;  // TCC 生成 shl 而非 imul
int x = a / 4;  // TCC 生成 sar 而非 idiv

// 窥孔：条件链去冗余
if (a < b && b < c)  // TCC 复用第一次比较的 flags
```

---

## 5. CCC — 自研 SSA IR

CCC 采取了一条中间路线：自研一套完整的 SSA IR，但保持其简洁和教学友好。

### 设计决策

CCC 的 IR 设计与 LLVM 的核心理念一致，但做了简化：

| 特征 | LLVM | CCC |
|------|------|-----|
| SSA 构造 | alloca → mem2reg | alloca → mem2reg (同样策略) |
| phi 节点 | 支持 | 支持 |
| 基本块 | `BasicBlock` 含 `Instruction` 列表 | 同样设计 |
| 类型系统 | 完整类型层次 | 双重：`CType` + `IrType` |
| 内存模型 | alloca + load/store + GEP | ptr + load/store（无 GEP，更简单） |

### CCC IR 的核心结构

```
IrFunction
├── name: String
├── params: Vec<IrReg>      // 函数参数（SSA 虚拟寄存器）
├── blocks: Vec<IrBlock>    // 基本块列表
│   ├── label: String
│   ├── phis: Vec<(IrReg, ...)>  // phi 节点
│   └── body: Vec<IrInstr>       // 指令列表
└── locals: Vec<IrReg>      // 局部变量（mem2reg 前是 alloca，后是 SSA reg）
```

### IR 指令示例

CCC 的 IR 指令是一个枚举，大约 30 种：

```rust
enum IrInstr {
    Add(IrReg, IrReg),          // r = a + b
    Sub(IrReg, IrReg),          // r = a - b
    Mul(IrReg, IrReg),          // r = a * b
    Icmp(Cond, IrReg, IrReg),   // r = a < b (产生 i1)
    Load(IrReg),                // r = *addr
    Store(IrReg, IrReg),        // *addr = val
    Call(String, Vec<IrReg>),   // r = func(args)
    Phi(Vec<(IrReg, String)>),  // phi [val, block]
    Br(IrReg, String, String),  // if cond { goto a } else { goto b }
    Jmp(String),                // goto block
    Ret(IrReg),                 // return val
    // ... 共约 30 种
}
```

### 双重类型系统

CCC 的一个独特设计是**将 C 语义类型和机器级类型分开**：

- `CType`：保留 C 语言的类型语义（`int` vs `long` 的区别、`const`、`volatile` 等），用于**语义分析**阶段的类型检查
- `IrType`：扁平的机器级类型枚举（`I8`, `I16`, `I32`, `I64`, `U8`, ..., `F32`, `F64`, `F128`, `Ptr`, `Void`），用于**IR 和代码生成**

```
C 代码:  const unsigned short x = 42;

CType:   UnsignedShort(const=true)       → 语义分析用
IrType:  U16                              → IR 和代码生成用
```

### mem2reg 在 CCC 中的实现

CCC 的 mem2reg 实现遵循标准算法：

```
1. 构建 CFG (控制流图)
2. 计算支配树 (dominator tree)
3. 计算支配边界 (dominance frontier) → 决定在哪里插入 phi 节点
4. 对每个 alloca:
   a. 在支配边界处插入 phi 节点
   b. 重命名：遍历支配树，为每个 store/load 替换为 SSA 寄存器
5. 删除无用的 alloca
```

这与 LLVM 的 mem2reg pass 本质上是同一个算法。

### 15 个优化 Pass

CCC 有 15 个 SSA 优化 pass，分为三组：

**Phase 0：内联相关**
```
inline → mem2reg → constant_fold → copy_prop → simplify
  → constant_fold → copy_prop → resolve_asm
```

**Main Loop（最多 3 轮，脏追踪）**
```
cfg_simplify → copy_prop → div_by_const → narrow → simplify
  → constant_fold → gvn → licm → iv_strength_reduce
  → if_convert → copy_prop → dce → cfg_simplify → ipcp
```

**清理**
```
dead_statics → phi elimination（SSA → 寄存器拷贝）
```

脏追踪（dirty tracking）：如果某个 pass 没有做任何修改，下游 pass 可以被跳过。

---

## 6. XCC — AST 即 IR

XCC 采取了与所有其他项目都不同的路线：**不降低 IR**。带类型标注的 AST 直接作为 IR 使用。

### 设计理念

XCC 的根本洞察是：对于 CPython（一个以可读性、可维护性和可移植性优先而非极致性能的 C 项目），自己维护一套 IR 和优化 pass 的性价比极低。

因此 XCC 的策略是：
1. 前端做到位置精确的语义分析和类型解析
2. 在 AST 上插入隐式转换节点（`ImplicitCast`）
3. 代码生成器直接遍历这个"丰富的 AST"，调用 libLLVM-C 函数
4. 所有优化委托给 LLVM 的 `llc`（内置优化 pass）

### AST 作为 IR 的可行性

| 传统 IR 要做的事 | XCC 的 AST 如何做到 |
|------------------|-------------------|
| 类型信息 | AST 节点在 Sema 阶段已关联 `Type` |
| 常量值 | `TypeMap` 中记录了 constexpr 的结果 |
| 控制流 | `IfStmt`, `ForStmt`, `WhileStmt` 等 AST 节点 |
| 函数调用 | `CallExpr` 节点 + `FunctionSymbol` |
| 隐式转换 | 显式插入的 `ImplicitCast` AST 节点 |

### 代码生成：AST → LLVM IR

XCC 的代码生成器 (`codegen.py`) 关键逻辑：

```python
class _LLVMGen:
    def visit_binary_expr(self, node: BinaryExpr) -> LLVMValueRef:
        left_val = self.visit(node.left)
        right_val = self.visit(node.right)
        op = node.op
        if op == "+":
            return LLVMBuildAdd(self.builder, left_val, right_val, b"")
        elif op == "-":
            return LLVMBuildSub(self.builder, left_val, right_val, b"")
        # ...

    def visit_if_stmt(self, node: IfStmt) -> None:
        cond = self.visit(node.condition)
        LLVMBuildCondBr(self.builder, cond, then_block, else_block)
        # ...

    def visit_call_expr(self, node: CallExpr) -> LLVMValueRef:
        func = self.resolve_function(node.name)
        args = [self.visit(a) for a in node.args]
        return LLVMBuildCall2(self.builder, func_type, func, args, b"")
```

### 优势与代价

**优势**：
- 理解简单：AST 是编译器开发者最熟悉的数据结构
- 调试友好：可以在 AST 层面打日志、断点
- 代码量少：不需要实现 SSA 构造、mem2reg、phi 消除等

**代价**：
- 不能在 XCC 内部做任何 IR 级优化（委托给 llc）
- 不能做 LTO（需要中间 IR 文件）
- 控制流（循环、分支）需要代码生成器自行管理基本块和跳转

---

## 总览对比表

| 特性 | LLVM IR | MLIR/ClangIR | GCC IR | TCC | CCC IR | XCC |
|------|---------|-------------|--------|-----|--------|-----|
| **IR 层级数** | 1 (LLVM IR) | N (dialect 链) | 3 (GENERIC→GIMPLE→RTL) | 0 | 1 (SSA IR) | 0 (AST 即 IR) |
| **是否 SSA** | 是 | 视 dialect | GIMPLE 阶段是 | N/A | 是 | N/A |
| **类型系统** | 强类型 | 视 dialect | 多级 (tree→RTL) | 运行时 | 双重 (CType/IrType) | Python `Type` |
| **优化位置** | IR 上 | 各 dialect 上 | GIMPLE+RTL 上 | 局部窥孔 | IR 上 (15 passes) | 委托 LLVM |
| **自建优化** | 全部 | 部分 | 全部 | 窥孔 | 15 passes | 0 |
| **自建后端** | 全部 | 部分 | 全部 (50+ arch) | x86/ARM/RISC-V | 4 arch + asm + linker | 0 (委托 LLVM) |
| **Phi 节点** | 支持 | 视 dialect | GIMPLE SSA | N/A | 支持 | N/A |

---

## 推荐的 IR 学习路线

如果你是初学者，建议按以下顺序理解 IR：

1. **从 XCC 开始**：理解 "AST 就是 IR" 意味着什么。手动在 AST 上插入转换节点，感受为什么需要更低级的表示。

2. **看 LLVM IR 的 `.ll` 输出**：用 `clang -S -emit-llvm hello.c` 生成文本 IR，阅读一个简单函数的 IR，理解 alloca/store/load 和 SSA 寄存器。

3. **研究 CCC 的 mem2reg**：CCC 代码干净，mem2reg 实现紧凑（~500 行），是理解 SSA 构造的最佳教材。

4. **理解 GIMPLE**：用 `gcc -fdump-tree-all` 导出 GCC 各 pass 的 GIMPLE dump，看一个简单函数在优化前后的变化。

5. **了解 MLIR 的思路**：不一定要写 MLIR 代码，但理解"不同的优化需要不同的抽象层级"这个思想。

---

下一站：[优化](optimization.md) — 当 IR 搭好后，编译器如何让代码跑得更快。
