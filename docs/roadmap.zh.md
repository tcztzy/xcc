# Roadmap

## 短期目标

- **消除 clang 回退**：让 `--backend=xcc` 独立编译全部 CPython 文件。
  - 当前状态：442/442 文件通过前端，432/442 通过原生 LLVM 后端。
  - 剩余 10 个文件需要完善代码生成。
- **增加更多 C11 特性**：
  - 可变参数函数（`va_list` / `va_start` / `va_end`）
  - 位域（bit-fields）
  - `_Complex` 类型
  - `_Atomic` 限定符

## 中期目标

- **Linux / ELF 支持**：通过同一套 libLLVM-C ctypes 路径支持 Linux 目标。
  - 当前仅支持 macOS ARM64（通过 Homebrew LLVM）。
- **Windows / PE 支持**：通过 LLVM 的 COFF 后端支持 Windows。
- **性能优化**：
  - 减少代码生成时的 Python 开销
  - 考虑将热路径用 Cython 或 Rust 重写

## 长期目标

- **自举**：用 XCC 编译 XCC（需要先编译 Python 解释器，或 XCC 移植到更底层语言）
- **LTO 支持**：生成 LLVM bitcode 而非文本 IR，支持链接时优化
- **调试信息**：生成 DWARF 调试信息，支持 LLDB 调试

## 已实现

- [x] C11 预处理（宏、头文件、条件编译、pragma）
- [x] 手写词法分析器（支持三字符组、行拼接）
- [x] 递归下降解析器（优先级爬升、完整声明符支持）
- [x] 语义分析（类型检查、符号表、隐式转换、常量求值）
- [x] LLVM IR 代码生成（libLLVM-C ctypes）
- [x] 三模式后端（xcc / auto / clang）
- [x] GNU 扩展（`__attribute__`、`typeof`、语句表达式、K&R 函数定义）
- [x] CPython 源码解析（442/442 文件通过前端）
- [x] CPython 部分编译（432/442 文件通过原生后端）
