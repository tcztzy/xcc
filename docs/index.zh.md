# 编译器构建指南

XCC 是一个用 Python 编写的 C11 编译器，零运行时依赖，通过 libLLVM-C (ctypes) 生成 LLVM IR，委托 llc + clang 产出机器码。

本文档通过对比 **GCC**、**Clang**、**TCC**、**CCC (Claude's C Compiler)** 和 **XCC** 五个项目，系统讲解编译器构建的全过程。

## 你将学到

- 编译器从 `.c` 到可执行文件的完整流水线
- 前端三阶段：预处理器 → 词法分析 → 语法分析
- 语义分析如何做类型检查和符号表管理
- **IR（中间表示）的核心作用**：LLVM IR、MLIR/ClangIR、GCC GIMPLE/RTL、CCC 自研 SSA IR、TCC 的无 IR 方案
- 优化 pass 的设计思路
- 后端如何将 IR 翻译为机器码

## 五个项目速览

| 项目 | 语言 | IR 方案 | 后端 | 目标 |
|------|------|---------|------|------|
| **GCC** | C/C++ | GENERIC → GIMPLE → RTL | 自研 50+ 架构 | 工业级，最大生态 |
| **Clang** | C++ | Clang AST → LLVM IR | LLVM 多架构 | 模块化，工具链生态 |
| **TCC** | C | **无显式 IR**（值栈） | 自研 x86/ARM/RISC-V | 极致编译速度 |
| **CCC** | Rust | 自研 SSA IR + mem2reg | 自研 4 架构 + 汇编器/链接器 | 全自举，零外部依赖 |
| **XCC** | Python | AST 即 IR → LLVM IR | LLVM (llc + clang) | 教学友好，CPython 自举 |

## 阅读顺序建议

1. [编译器流水线总览](pipeline-overview.md) — 建立全局视角
2. [前端](frontend.md) — 预处理器、词法分析、语法分析
3. [语义分析](semantic-analysis.md) — 类型检查与符号表
4. [IR 全景对比](ir-landscape.md) — 五种 IR 方案的设计哲学 *(核心页面)*
5. [优化](optimization.md) — 优化 pass 的设计
6. [后端与代码生成](backend.md) — 从 IR 到机器码
7. [五编译器横向对比](compiler-comparison.md) — 一览表
8. [XCC 架构详解](xcc-architecture.md) — 本项目深度解析
9. [学习路径](learning-path.md) — 推荐书籍与项目

## 快速开始

```
uv run mkdocs serve    # 本地预览文档
uv run mkdocs build    # 构建静态站点
```
