# XCC 架构

XCC 是一个 Python 3.11+、运行时仅依赖标准库的 C11/GNU11 编译器。它采用一条共享前端和四个显式目标，不把 CPython、宿主编译器或备用后端藏进编译路径。

## 主编译路径

```text
CLI / CC driver
       │
       ▼
preprocessor → lexer → parser → sema
                              │
                              ▼
                       FrontendResult
                              │
          ┌───────────┬───────┼───────────┐
          ▼           ▼       ▼           ▼
        LLVM       AArch64   x86-64       EVM
          │           │       │           │
         llc        assembler/linker      bytecode
```

- `frontend.py` 只编排预处理、词法、语法和语义阶段，并统一把阶段错误转换成带源码位置的诊断。
- `cc_driver.py` 只负责参数、目标选择、产物和工具调用。它不修补前端语义，也不调用隐藏的备用编译器。
- `preprocessor/`、`parser/` 和 `sema/` 各自由包入口中的状态对象拥有可变状态；同包 helper 是处理一种语义的具体函数，不另造虚假的抽象接口。
- `ast.py` 是 C 语法树的唯一表示；`types.py` 是语义类型的唯一表示。两者都用有序 `declarator_ops` 表达指针、数组和函数声明符，没有并行的旧字段。
- 语义分析不重写 AST。表达式类型存入 `TypeMap`，记录布局、符号和函数签名存入 `SemaUnit`，后端只消费 `FrontendResult`。
- `TranslationUnit.source_map` 按节点身份支持语义诊断的随机查询；`source_locations` 按前序保存调试位置，避免 AOT 阶段搬移对象后失效的整数身份。
- `data_layout.py` 是大小、对齐和目标整数模型的共享事实源。

## 后端边界

`codegen.py`、`aarch64_asm.py`、`x86_64_asm.py` 和 `evm.py` 是四个互不回退的叶子后端。共享的只有 AST 遍历、类型、布局和语义结果；ABI、寄存器、指令与产物格式留在所属目标中。

LLVM 目标通过 `llvm_api.py` 生成 IR，并由 `llvm_tools.py` 验证后选择 `llc`。原生 AArch64、x86-64 和 EVM 直接生成各自输出。某目标不支持的构造必须报错，不能悄悄换目标。

这些后端文件较大，但不是重复层：每个文件拥有一个目标的完整降低状态。仅按行数拆分会把寄存器、栈帧和控制流状态扩散到更多模块。真正跨目标重复的无状态逻辑才进入共享模块，例如 `walk_ast_children`。

## AOT / 自举路径

AOT 是编译器自身的 Python 子集编译器，不是 C 前端的第二份实现：

```text
Python source
  → owned Python lexer/parser (`py_lexer.py`, `py_parser.py`, `py_ast.py`)
  → subset check + binding + analysis
  → reachable slice
  → typed AOT IR (`ir.py`, `lower.py`)
  → LLVM text + native runtime
  → native compiler / bootstrap
```

`source_contract.py` 决定源集和可达边界，`slice.py` 只保留入口可达代码，`lower.py` 负责 Python 子集到 AOT IR，`llvm_text.py` 与 `core_runtime.py` 共同拥有原生表示和运行时。固定的 Darwin ARM64 bootstrap 工具布局是该产物边界的显式约定，不是通用 driver 的兼容分支。

## 测试边界

测试按可观察契约分层：

1. 用最小 C/Python 源码测试 parser、sema 和预处理语义。
2. 用公开 CLI 与产物测试 driver 和各目标。
3. 用执行结果、LLVM 工具、宿主 oracle 和真实 CPython 构建验证跨阶段行为。
4. 用 hosted/native/bootstrap 对照验证 AOT 自举闭包。

同一语义只在拥有它的最低阶段精确断言一次，上层仅保留集成价值。测试不伪造生产路径不可能产生的 AST/IR，不检查源码形状，也不为覆盖率数字制造分支。覆盖率是观察值，不是保留冗余测试的理由。

## 结论

这是合格的模块化编译器架构：前端阶段、共享语义、目标后端和 AOT 自举边界清楚；导入时依赖图无环；现有模块均有入口或被生产路径引用，没有可删除的冗余模块。

限制也明确：几个目标后端和 AOT lowering/runtime 是大型叶子，修改成本高；原生后端直接消费 AST + `TypeMap`，没有独立的共享 C IR。当前目标数量下，这比为了形式上的小文件引入转发层更简单。只有出现第二个真实消费者或跨目标重复语义时，才应继续抽取模块。
