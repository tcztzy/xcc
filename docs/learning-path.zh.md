# 学习路径

一名有基本计算机知识的人如何逐步掌握编译器构建？以下是推荐的路径。

## 第一阶段：理解编译的基本流程

**目标**：能解释 `.c → 可执行文件` 的完整过程。

**资源**：
1. 阅读本项目的 [编译器流水线总览](pipeline-overview.md)
2. [Crafting Interpreters](https://craftinginterpreters.com/)（免费在线书）
   - 先看前半部分（解释器），理解 lexer/parser/AST 的基本实现
   - 用 Java 或 C 实现，但 Python 也可以
3. 手写一个**四则运算计算器**
   - 实现 lexer（`"3 + 4 * (2 - 1)"` → `[NUM(3), PLUS, NUM(4), STAR, LPAREN, NUM(2), MINUS, NUM(1), RPAREN]`）
   - 实现 parser（递归下降或优先级爬升）
   - 实现 evaluator（遍历 AST 计算结果）
   - **这只需要 ~200 行代码，但涵盖了编译前端的核心概念**

## 第二阶段：手写一个迷你 C 编译器

**目标**：能编译 `int main() { return 42; }` 到 x86-64 汇编。

**资源**：
1. 研究 **TCC** 的源码（`~/GitHub/tinycc/tccgen.c`）
   - 特别是 `expr_xxx()` 函数系列：表达式解析 + 代码生成的合并方式
   - 理解值栈 (`vstack`) 如何替代显式 IR
2. 研究 **XCC** 的源码 (`src/xcc/lexer.py`, `src/xcc/parser/`, `src/xcc/sema/`)
   - XCC 的代码在 Python 中非常可读
   - 从 `lexer.py` 开始，然后看 `parser/expressions.py` 的优先级爬升
3. 建议的项目步骤：
   1. 实现 lexer（支持 int, return, 字面量, `{}()`, `;`）
   2. 实现解析器（支持函数定义和 return 语句）
   3. 实现代码生成（x86-64 汇编模板：`mov eax, 42; ret`）
   4. 扩展支持二元运算（`+ - * /`）
   5. 扩展支持局部变量

## 第三阶段：理解 IR 和优化

**目标**：理解 SSA 形式、mem2reg、基本优化 pass。

**资源**：
1. 阅读本项目的 [IR 全景对比](ir-landscape.md)
2. **LLVM IR 实战**：
   ```bash
   echo 'int add(int a, int b) { return a + b; }' | \
     clang -x c -S -emit-llvm -o - -
   ```
   阅读输出，理解 alloca/store/load 和 SSA 的区别。
   ```bash
   clang -x c -S -emit-llvm -O2 -o - -  # 看优化后的差异
   ```

3. 研究 **CCC** 的 IR 子系统 (`~/GitHub/claudes-c-compiler/src/ir/`)
   - `lowering/`：AST → alloca-based IR
   - `mem2reg/`：alloca → SSA (支配树 + phi 插入 + 重命名)
   - 这是理解 SSA 构造的最佳代码示例

4. 研究 **CCC** 的优化 passes (`~/GitHub/claudes-c-compiler/src/passes/`)
   - `constant_fold`（常量折叠，最简单）
   - `dce`（死代码消除）
   - `gvn`（全局值编号，较复杂但威力大）

5. **LLVM 的 Kaleidoscope 教程**（[在线](https://llvm.org/docs/tutorial/)）
   - 用 C++ 从零实现一个小语言（包括 JIT），直接调用 LLVM API
   - 完整覆盖：lexer → parser → IR → JIT → optimizer

## 第四阶段：深入后端

**目标**：理解寄存器分配、指令选择、汇编和链接。

**资源**：
1. **《Engineering a Compiler》**（Keith Cooper & Linda Torczon）
   - 第 13 章：指令选择（树模式匹配）
   - 第 14 章：寄存器分配（图着色 + 线性扫描）
   - 第 12 章：指令调度

2. 阅读本项目的 [后端与代码生成](backend.md)

3. 研究 **CCC** 的代码生成和汇编器：
   ```
   ~/GitHub/claudes-c-compiler/src/backend/
   ├── regalloc.rs         # 线性扫描寄存器分配
   ├── liveness.rs         # 存活区间计算
   ├── generation.rs       # IR → 汇编指令分发
   └── x86/codegen/        # x86-64 SysV ABI 实现
   ```

4. 研究 **TCC** 的代码生成：
   ```
   ~/GitHub/tinycc/x86_64-gen.c   # x86-64 代码生成（~3000 行）
   ```

## 第五阶段：阅读工业级编译器

**目标**：理解真实世界编译器的全貌。

**资源**：
1. **Clang 源码** (`https://github.com/llvm/llvm-project/tree/main/clang`)
   - `lib/Lex/`：Preprocessor 和 Lexer
   - `lib/Parse/`：Parser（递归下降，表驱动）
   - `lib/Sema/`：语义分析（最复杂）
   - `lib/CodeGen/`：Clang AST → LLVM IR

2. **GCC 源码** (`https://gcc.gnu.org/git.html`)
   - `gcc/c/`：C 前端
   - `gcc/tree-ssa*.cc`：GIMPLE SSA 优化 pass
   - `gcc/config/`：目标架构后端

3. **LLVM 源码** (`https://github.com/llvm/llvm-project/tree/main/llvm`)
   - `lib/Transforms/Scalar/`：标量优化 pass
   - `lib/CodeGen/`：Machine IR 和寄存器分配

## 推荐书籍

| 书籍 | 难度 | 适合阶段 |
|------|------|----------|
| [Crafting Interpreters](https://craftinginterpreters.com/) | ★★ | 第一阶段：入门 |
| [Writing a C Compiler](https://norasandler.com/2017/11/29/Write-a-Compiler.html) (博客系列) | ★★ | 第二阶段：实现 C 编译器 |
| [LLVM Kaleidoscope Tutorial](https://llvm.org/docs/tutorial/) | ★★★ | 第三阶段：LLVM IR |
| [Engineering a Compiler](https://www.elsevier.com/books/engineering-a-compiler/cooper/978-0-12-815412-0) | ★★★★ | 第四-五阶段：深入 |
| [SSA-based Compiler Design](https://link.springer.com/book/10.1007/978-3-030-80515-9) | ★★★★ | 第三阶段：SSA 理论 |
| [Advanced Compiler Design and Implementation](https://www.amazon.com/Advanced-Compiler-Design-Implementation-Muchnick/dp/1558603204) | ★★★★★ | 第五阶段：工业级 |

## 项目源码阅读顺序

如果你要通读这五个编译器的源码，建议顺序是：

1. **TCC** → 最简单，15K 行，理解单遍编译
2. **XCC** → Python 可读性强，理解模块化设计
3. **CCC** → Rust 干净现代，理解 SSA IR + 优化管线
4. **Clang** → 最好的工业编译器文档
5. **GCC** → 最完整但最难入门

## 动手项目建议

这些项目的难度递增：

| 项目 | 预计代码量 | 学习重点 |
|------|-----------|----------|
| 1. 四则运算计算器 | ~200 行 | Lexer + Parser 基础 |
| 2. 迷你解释型语言 | ~500 行 | 变量、作用域、控制流 |
| 3. C 子集 → x86 汇编 | ~1500 行 | 代码生成、栈帧、ABI |
| 4. 自研 SSA IR | ~3000 行 | mem2reg、phi 节点、优化 pass |
| 5. 完整 C 编译器 | ~15000 行 | 前端完整性、预处理器、链接 |

---

[回到首页](index.md)
