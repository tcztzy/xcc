# Roadmap

## 短期目标

- **真实项目集成**：`CC="xcc" ./configure && make` 在没有 CPython 专用编译器路径的情况下工作。
  - CPython 保留为旗舰集成目标。
  - 失败应转化为通用的最小 C 回归测试。
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
- [x] 目标模型，默认 `--target=llvm`
- [x] GNU 扩展（`__attribute__`、`typeof`、语句表达式、K&R 函数定义）
- [x] CPython 源码解析（442/442 文件通过前端）
- [x] CPython 构建作为旗舰集成目标
