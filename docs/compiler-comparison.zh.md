# 五编译器横向对比

一张表看清 GCC、Clang、TCC、CCC 和 XCC 的所有关键维度。

## 基本信息

| 维度 | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **语言** | C/C++ | C++ | C | Rust | Python |
| **首次发布** | 1987 | 2007 | 2002 | 2025 | 2025 |
| **许可证** | GPLv3+ | Apache 2.0 | LGPLv2 | CC0-1.0 | Apache 2.0 |
| **代码量 (估算)** | ~15M 行 | ~5M 行 | ~15K 行 | ~100K 行 | ~21K 行 |
| **维护者** | GNU 项目 | LLVM 基金会 | Fabrice Bellard + 社区 | Anthropic (AI 生成) | 个人 |

## 设计哲学

| 维度 | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **目标** | 最广泛的平台 + 最佳优化 | 模块化工具链 + 错误信息好 | 极致编译速度 | 全自举零依赖 | Agent 管控工程 + CPython 规模验证 |
| **依赖** | GMP, MPFR, MPC, ISL, binutils | LLVM 库, 可选 libc++ | 无外部编译依赖 | 零编译器依赖 | Python 3.11+ 标准库运行时；LLVM 工具仅用于 LLVM target |
| **编译速度 (粗略)** | 慢 (大量优化) | 中等 | **极快** (~5-10x GCC) | 中等 | 慢 (Python + 委托 LLVM) |
| **输出代码速度** | **极快** | 很快 | 较慢 (仅窥孔优化) | 快 (15 pass 管线) | 取决于目标：LLVM 或原生直接发射 |

## 流水线

| 阶段 | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **预处理器** | libcpp（token 流） | `clang::Preprocessor` | `tccpp.c` (文本流) | Rust 手写 | Python 手写 |
| **词法分析** | libcpp 内 | `clang::Lexer` | 合并 `tccpp.c` | Rust 手写 | `lexer.py` |
| **语法分析** | 递归下降 + 部分 bison | 递归下降 (表驱动) | 递归下降 | 递归下降 | 递归下降 (优先级爬升) |
| **语义分析** | ~50K 行 C | ~15K 行 C++ | 合并 gen (~9K 行) | ~3K 行 Rust | ~4.9K 行 Python |
| **IR** | GENERIC→GIMPLE→RTL | LLVM IR | **无**（值栈） | 自研 SSA IR | AST 即 IR |
| **优化** | 300+ passes | 150-170 passes (O2) | 局部窥孔 | 15 passes (3 组) | 委托 LLVM |
| **代码生成** | expand (GIMPLE→RTL) + asm | llc (LLVM IR→MC) | 边解析边 emit | ArchCodegen trait × 4 | AST 降低到 LLVM IR、原生汇编或 EVM 字节码 |
| **汇编** | GAS / 内联 | 集成汇编器 / GAS | 自研 | 自研 (四架构) | LLVM 通过 `llc`；原生和 EVM 目标直接发射 |
| **链接** | collect2 + GNU ld | lld / 系统 ld | 自研 ELF/PE/Mach-O | 自研 (四架构) | hosted 目标走系统汇编/链接；EVM 写出字节码 |

## IR 对比

| 特性 | LLVM IR | GCC IR (GIMPLE) | TCC | CCC IR | XCC |
|------|---------|-----------------|-----|--------|-----|
| **SSA 形式** | 是 | GIMPLE 阶段是 | N/A | 是 | N/A |
| **Phi 节点** | 有 | 有 (虚拟操作数) | N/A | 有 | N/A (AST 无 phi) |
| **mem2reg** | 是 | 是 | N/A | 是 | N/A |
| **类型系统** | 强类型 | 多级 (tree→RTL) | 运行时 | 双重 (CType/IrType) | Python Type |
| **IR 文件格式** | .ll / .bc | .gimple dump | N/A | 无持久化格式 | N/A |
| **中间产物** | bitcode (.bc) 支持 LTO | .s (汇编文本) | N/A | 无 | LLVM IR 字符串 |

## 后端支持

| 架构 | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **x86-64** | 是 | 是 | 是 | 是 | 原生 Linux + LLVM target |
| **x86 (i386/i686)** | 是 | 是 | 是 | 是 (i686) | 有工具链/sysroot 时可走 LLVM target |
| **ARM (32-bit)** | 是 | 是 | 是 | 否 | 有工具链/sysroot 时可走 LLVM target |
| **AArch64 (ARM64)** | 是 | 是 | 是 | 是 | 原生 Darwin + LLVM target |
| **RISC-V (32/64)** | 是 | 是 | 是 | 是 (RV64) | 有工具链/sysroot 时可走 LLVM target |
| **MIPS** | 是 | 是 | 否 | 否 | 有工具链/sysroot 时可走 LLVM target |
| **PowerPC** | 是 | 是 | 否 | 否 | 有工具链/sysroot 时可走 LLVM target |
| **总计** | **50+** | **20+** | **5** | **4** | **4 个显式目标 + LLVM target 路径** |

## 生态与工具

| 工具 | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **调试器** | GDB | LLDB | GDB | GDB (DWARF 自产) | LLDB/lldb |
| **静态分析** | `-fanalyzer` | Clang Static Analyzer | 无 | 无 | 无 |
| **Sanitizer** | ASan, TSan, UBSan | ASan, TSan, UBSan, MSan | 无 | 无 | 无 (依赖 clang) |
| **LTO** | 是 (fat LTO / slim LTO) | 是 (ThinLTO / FullLTO) | 否 | 否 | 否 (依赖 LLVM) |
| **PGO** | 是 | 是 | 否 | 否 | 否 |
| **LSP/IDE** | gcc + clangd | clangd | 无 | 无 | clangd |
| **包管理集成** | 所有构建系统 | 所有构建系统 | 部分 (make/cmake) | 部分 (drop-in GCC) | CC 风格 driver，按宿主平台选择默认目标 |

## 特色能力

| 能力 | GCC | Clang | TCC | CCC | XCC |
|------|-----|-------|-----|-----|-----|
| **C11 支持** | 完整 | 完整 | 基本 | 大部分 | 大部分 |
| **C23 支持** | 实验性 | 大部分 | 否 | 否 | 否 |
| **GNU 扩展** | 全部 | 大部分 | 部分 | 部分 | 部分 |
| **C++ 支持** | 是 (完整) | 是 (完整) | 否 | 否 | 否 |
| **自举** | 是 | 是 (编译 LLVM) | 是 | 是 (编译 Linux) | 否 |
| **JIT 编译** | libgccjit | LLVM OrcJIT | tcc -run | 否 | 否 |
| **交叉编译** | 是 (需要 sysroot) | 是 (sysroot) | 是 (sysroot) | 是 (sysroot) | 显式 target；LLVM 路径需要 `llc` 和 sysroot |

## 适合的学习场景

| 如果你想学... | 推荐看 | 原因 |
|--------------|--------|------|
| 工业级编译器实现 | GCC | 最完整的参考实现 |
| 模块化编译器架构 | Clang | 清晰的模块边界，丰富的文档 |
| 单遍编译器原理 | TCC | 代码极少 (~15K)，逻辑直白 |
| SSA IR 和优化 | CCC | 干净的 Rust 代码，15 个 pass 容易理解 |
| Agent 管控下的编译器工程 | XCC | 规格、测试、oracle、负边界和 handoff gates 是一等约束 |

---

## 一句话总结

| 项目 | 一句话 |
|------|--------|
| **GCC** | 工业标杆，300+ 个优化 pass，50+ 架构支持，庞杂但无所不能 |
| **Clang** | 模块化的 LLVM 前端，API 驱动的工具链生态，错误信息业界最好 |
| **TCC** | 极简主义的胜利——15K 行代码，能编译 Linux 内核，速度快 5-10x |
| **CCC** | AI 生成的奇迹——全自举，从预处理器到链接器全部手写，四个架构 |
| **XCC** | Python 3.11+ 标准库 C11 编译器，同时是用规格、测试、oracle 和负边界管控 coding agent 的工程样板 |

---

下一站：[XCC 架构详解](xcc-architecture.md) — 深入本项目的实现细节。
