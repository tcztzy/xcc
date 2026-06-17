# Roadmap

## 短期目标

- **公开证据链**：保持 CI、validation、lint、type 和 Pages 部署门禁为绿，
  让 XCC 的 agent-control 主张可以被复现。
- **回归转化**：把 CPython 暴露的问题转成通用的最小 C 或 CLI 复现，并配上
  clang、`llc`、诊断、执行结果或真实构建 oracle。
- **C11/GNU 边界覆盖**：继续补齐真实系统头文件和 CPython 规模构建暴露的前端
  与目标后端缺口。

## 中期目标

- **目标矩阵加固**：让 LLVM、原生 Darwin AArch64、原生 Linux x86_64 和
  EVM 输出都有聚焦的 smoke checks。
- **Windows / PE 支持**：评估通过 LLVM COFF 输出或未来原生路径支持 Windows。
- **性能优化**：
  - 减少前端和目标降低热路径里的 Python 开销
  - 保持 Cython 和 mypyc 为可选 benchmark 变体，而不是运行时依赖

## 长期目标

- **自举**：用 XCC 编译 XCC（需要先编译 Python 解释器，或 XCC 移植到更底层语言）
- **LTO 支持**：生成 LLVM bitcode 而非文本 IR，支持链接时优化
- **调试信息**：生成 DWARF 调试信息，支持 LLDB 调试

## 已实现

- [x] C11 预处理（宏、头文件、条件编译、pragma）
- [x] 手写词法分析器（支持三字符组、行拼接）
- [x] 递归下降解析器（优先级爬升、完整声明符支持）
- [x] 语义分析（类型检查、符号表、隐式转换、常量求值）
- [x] LLVM IR target（libLLVM-C ctypes 加已验证 `llc` object lowering）
- [x] 按宿主平台选择默认目标，并显式支持 `llvm`、`aarch64-apple-darwin`、`x86_64-linux-gnu` 和 `evm`
- [x] 原生 Darwin AArch64 与原生 Linux x86_64 的 CPython 规模构建支持
- [x] GNU 扩展（`__attribute__`、`typeof`、语句表达式、K&R 函数定义）
- [x] CPython 源码解析（442/442 文件通过前端）
- [x] CPython 构建作为旗舰集成目标
- [x] Agent-control 文档、验证脚本和 GitHub Pages landing page
