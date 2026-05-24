# 编译器流水线总览

所有 C 编译器都遵循相同的基本流水线结构，但在具体实现上各有取舍。本章建立全局视角。

## 通用流水线

```
C 源文件 (.c, .h)
     │
     ▼
┌─────────────┐
│  预处理器    │  宏展开、头文件包含、条件编译
└─────────────┘
     │  预处理后的 C 文本
     ▼
┌─────────────┐
│  词法分析    │  文本 → Token 流
└─────────────┘
     │  Token 序列
     ▼
┌─────────────┐
│  语法分析    │  Token → AST
└─────────────┘
     │  AST (抽象语法树)
     ▼
┌─────────────┐
│  语义分析    │  类型检查、符号表、常量求值
└─────────────┘
     │  带类型标注的 AST
     ▼
┌─────────────┐
│ 中间表示(IR) │  AST → 更低级表示（SSA / 三地址码 / 值栈）
└─────────────┘
     │  IR 模块
     ▼
┌─────────────┐
│  优化 (可选)  │  死代码消除、内联、常量折叠等
└─────────────┘
     │  优化后的 IR
     ▼
┌─────────────┐
│  代码生成    │  IR → 汇编 / 机器码
└─────────────┘
     │  汇编 / 目标文件
     ▼
┌─────────────┐
│  汇编 / 链接  │  目标文件 + 库 → 可执行文件
└─────────────┘
     │
     ▼
  可执行文件 (ELF / Mach-O / PE)
```

## 五个项目的流水线对比

### GCC

```
.c → [cpp] → GENERIC树 → GIMPLE(SSA) → 多轮优化 → RTL → 汇编 → .o → ld → executable
                  │                              │                │
                  └─ 语言无关的通用树            └─ 目标相关       └─ GNU binutils
```

GCC 的独特之处在于 **三层 IR**：
- **GENERIC**：从语言前端 AST 转换来的语言无关树表示
- **GIMPLE**：三地址码形式（`a = b + c`），SSA 形式下做优化
- **RTL**：寄存器传输语言，接近汇编，处理目标架构细节

### Clang / LLVM

```
.c → [clang] → Clang AST → LLVM IR → opt(优化) → llc → .o → lld/clang → executable
                     │           │           │          │
                     └─ 丰富AST   └─ SSA      └─ 可选    └─ LLVM 工具链
```

Clang 的设计理念是 **一种 IR 打通全流程**。优化、JIT、静态编译、链接时优化 (LTO) 都在同一套 IR 上操作。

ClangIR (CIR) 是一个正在孵化中的 **更高层 IR**，位于 Clang AST 和 LLVM IR 之间，用 MLIR 构建，保留 C/C++ 语义。

### TCC

```
.c → [cpp+lex+parse+gen] (单次遍历) → x86/ARM 机器码 → .o → ld → executable
        │                                      │
        └─ 边解析边生成                           └─ 自研 binder (可选 GNU ld)
```

**TCC 没有显式 IR。** 语法分析器边解析 C 代码边调用代码生成器，通过**值栈 (vstack)** 管理中间结果。这是极致编译速度的代价——牺牲了全局优化能力。

### CCC (Claude's C Compiler)

```
.c → [prep→lex→parse→sema] → alloca IR → mem2reg → SSA IR → 15 passes → non-SSA → 汇编 → .o → ELF
                                               │         │                         │        │
                                               └─ 栈分配  └─ GVN/LICM/inline...    └─ 自研  └─ 自研
```

CCC 的独特之处在于 **完全自举**：自研汇编器、链接器，四架构后端 (x86-64, i686, AArch64, RISC-V 64)，零外部编译器依赖。IR 采用与 LLVM 相同的 allocas → mem2reg → SSA 路线。

### XCC (本项目)

```
.c → [prep→lex→parse→sema] → 带类型的 AST → LLVM IR (libLLVM-C ctypes) → llc → .o → clang → executable
                                                      │                          │       │
                                                      └─ 程序化调用 C API        └─ llc   └─ clang
```

XCC 的 AST **即是 IR**——代码生成器直接遍历语义分析后的 AST，通过 libLLVM-C 的 ctypes 绑定构建 LLVM IR。然后委托 LLVM 工具链完成优化和代码生成。

## 设计取舍的空间

| 维度 | 极端 | 另一端 |
|------|------|--------|
| 编译速度 | TCC（单遍，无 IR） | GCC（多遍，多层 IR） |
| 代码质量 | CCC/GCC（15+ passes） | TCC（仅局部窥孔） |
| 架构可移植性 | LLVM（统一 IR，多后端） | TCC（每个架构手写代码生成） |
| 依赖复杂度 | GCC/LLVM（庞大工具链） | TCC/CCC（几乎零外部依赖） |
| 教学友好度 | XCC（Python + AST 即 IR） | GCC（庞杂内部实现） |

下一页我们深入前端的第一站：[预处理器、词法分析和语法分析](frontend.md)。
