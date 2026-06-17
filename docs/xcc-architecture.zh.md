# XCC 架构详解

XCC 是一个用 Python 3.11+ 标准库实现的 C11 编译器，也是一个展示如何用规格、测试、oracle 和负边界把 coding agent 管控在预期行为内的工程样板。实现仍然保持可读，但项目组织已经围绕 CPython 规模验证和显式 agent 控制展开。

## 设计目标

1. **Python 3.11+ 标准库运行时**：没有运行时包依赖
2. **编译真实 C 项目**：CPython 是旗舰集成测试，不是特殊路径
3. **目标自有输出路径**：LLVM、Darwin AArch64、Linux x86_64 和 EVM 都是显式目标，没有隐藏 fallback compiler
4. **Agent-control 工程**：行为写入 specs、tests、oracles、负边界、`CHANGELOG.md` 和 `LESSONS.md`

## 源码总览

```
src/xcc/                         (~21,000 行 Python，41 个文件)
├── __init__.py              CLI 入口 (main)
├── options.py               FrontendOptions 数据类
├── cc_driver.py             CC 兼容模式 (-c, -S, -E, -o)
├── frontend.py              前端流水线编排
├── diag.py                  诊断 / 错误类型
├── lexer.py                 手写 C11 词法分析器 (~570 行)
├── ast.py                   AST 节点定义 (~410 行)
├── types.py                 语义类型表示 (~150 行)
├── llvm_api.py              原始 libLLVM-C ctypes 绑定 (~700 行)
├── codegen.py               AST → LLVM IR 降低 (~4500 行)
├── aarch64_asm.py           原生 Darwin AArch64 汇编目标
├── x86_64_asm.py            原生 Linux x86_64 汇编目标
├── evm.py                   Ethereum EVM 汇编/字节码目标
├── host_includes.py         macOS SDK 头文件路径探测
│
├── parser/                  递归下降 C11 解析器 (~4500 行)
│   ├── __init__.py          Parser 主类
│   ├── expressions.py       表达式解析 (优先级爬升)
│   ├── statements.py        语句解析
│   ├── type_specs.py        类型说明符解析
│   ├── declarators.py       声明符解析
│   ├── array_sizes.py       数组大小求值和诊断
│   └── extensions.py        GNU/MSVC 扩展
│
├── sema/                    语义分析 (~5000 行)
│   ├── __init__.py          Analyzer 主类
│   ├── symbols.py           符号表 / TypeMap / SemaUnit
│   ├── declarations.py      声明分析
│   ├── statements.py        语句类型检查
│   ├── expressions.py       表达式类型解析
│   ├── type_resolution.py   TypeSpec → Type
│   ├── type_helpers.py      整数等级、提升、算术转换
│   ├── conversions.py       隐式转换规则
│   ├── constants.py         整型常量表达式求值
│   ├── records.py           记录 (struct/union) 布局
│   ├── layout.py            sizeof / alignof 计算
│   ├── initializers.py      初始化列表分析
│   └── format_checking.py   格式化字符串检查
│
└── preprocessor/             C 预处理器 (~4200 行)
    ├── __init__.py          _Preprocessor、错误、源码位置
    ├── text.py              指令解析
    ├── macros.py            宏定义结构
    ├── macro_expansion.py   宏展开引擎
    ├── expressions.py       #if 表达式求值
    ├── conditionals.py      条件编译栈
    ├── includes.py          #include 路径解析
    ├── probes.py            __has_include 等
    └── pragmas.py           #pragma 处理
```

## 文件间调用关系

```
                          __init__.py (CLI)
                               │
                    ┌──────────┼──────────┐
                    ▼                     ▼
              frontend.py           cc_driver.py
              (完整流水线)          (CC 兼容接口)
                    │                     │
         ┌─────────┤                     │
         ▼         │                     │
   options.py      │                     │
                   │                     │
         ┌─────────┼──────────┐         │
         ▼         ▼          ▼         │
   preprocessor/   lexer.py   parser/    │
         │         │          │         │
         │         └────┬─────┘         │
         │              ▼               │
         │          parser/             │
         │              │               │
         │         ┌────┴─────┐        │
         │         ▼          ▼        │
         │     sema/      ast.py + types.py
         │         │                    │
         │    ┌────┴─────┐             │
         │    ▼          ▼             │
         │  symbols.py  declarations.py│
         │  expressions.py  ...        │
         │         │                    │
         │    FrontendResult           │
         │         │                    │
         └────┬────┘                    │
              ▼                         │
        target backend                  │
   ┌──────────┼──────────┐              │
   ▼          ▼          ▼              ▼
codegen.py  aarch64_asm.py  x86_64_asm.py  evm.py
LLVM IR    Darwin asm      Linux asm      EVM asm/bin
   │          │             │              │
   ▼          ▼             ▼              ▼
  llc      system tools  system tools   bytecode output
```

## 关键设计决策

### 1. AST 用 frozen dataclass

```python
@dataclass(frozen=True)
class BinaryExpr:
    op: str
    left: Expr
    right: Expr
```

`frozen=True` 意味着 AST 节点创建后不可变。这防止了 parser 或 sema 意外修改 AST，也使得 AST 节点可哈希（可以用作 dict key，例如 `TypeMap` 中 node → type 的映射）。

### 2. 隐式转换显式插入

在语义分析阶段，当发现类型不匹配时，分析器**向 AST 中插入 `ImplicitCast` 节点**：

```python
@dataclass(frozen=True)
class ImplicitCast(Expr):
    expr: Expr            # 被转换的表达式
    target_type: Type     # 目标类型
    cast_kind: str        # "lvalue_to_rvalue" | "integral_promotion" | ...
```

这避免了代码生成器处理类型转换逻辑——它只需要机械地翻译每个节点。

### 3. 目标驱动代码生成

XCC 使用目标选择，而不是后端模式。在 x86_64 Linux 宿主上，driver 默认选择
`x86_64-linux-gnu`；其他宿主默认选择 `llvm`。不支持的目标会在编译源码前被拒绝：

```python
# 宿主默认目标：
#   x86_64 Linux -> x86_64-linux-gnu
#   其他宿主      -> llvm

# 显式 target：
#   xcc --target=llvm -c file.c -o file.o
#   xcc --target=aarch64-apple-darwin -c file.c -o file.o
#   xcc --target=x86_64-linux-gnu -c file.c -o file.o
#   xcc --target=evm -c file.c -o file.bin

# -S 写出目标汇编语言。
# 对 target=llvm，这意味着文本 LLVM IR。
```

### 4. Opaque Pointer

XCC 使用 LLVM 15+ 的 opaque pointer 特性——所有指针类型统一为 `ptr`（在 LLVM-C API 中为 `LLVMPointerType(i8, 0)`），不再区分 `i32*` vs `i64*`。这简化了类型映射和 GEP 操作。

### 5. 类型化 helper 模块契约

大型 parser、preprocessor、sema helper 保持在聚焦的小模块里，但入口使用窄
`Protocol` 契约，而不是无类型 `Any`。这样主类仍然负责状态，helper 依赖也能被
`ty check` 看到。

### 6. 内置函数处理

XCC 对 C 标准中的 `__builtin_*` 函数做特殊处理：

```python
def _emit_builtin_call(self, name: str, args: list) -> LLVMValueRef | None:
    if name == "__builtin_memset":
        return LLVMBuildMemSet(self.builder, ptr, val, size, align)
    if name == "__builtin_memcpy":
        return LLVMBuildMemCpy(self.builder, dst, src, size, align)
    # ... 直接映射到 LLVM 内建 intrinsic
    return None  # 未识别的 builtin，作为普通函数调用
```

## 类型系统

XCC 的类型系统 (`types.py`) 使用一个统一的 `Type` 数据类：

```python
@dataclass(frozen=True)
class Type:
    kind: TypeKind      # INT | PTR | ARRAY | FUNC | RECORD | VOID | ...
    modifiers: int      # bitmask: CONST | VOLATILE | RESTRICT
    # kind-specific fields:
    subtype: Type | None          # 指针目标类型 / 数组元素类型
    array_size: int | None        # 数组大小
    param_types: tuple[Type, ...] # 函数参数类型
    return_type: Type | None      # 函数返回类型
    record_name: str | None       # struct/union 名称
    # 整数类型细节：
    int_size: int                 # 位宽 (8, 16, 32, 64)
    int_signed: bool              # 是否有符号
```

预定义的常用类型别名：

```python
INT = Type(kind=TypeKind.INT, int_size=32, int_signed=True)
UINT = Type(kind=TypeKind.INT, int_size=32, int_signed=False)
LONG = Type(kind=TypeKind.INT, int_size=64, int_signed=True)
CHAR = Type(kind=TypeKind.INT, int_size=8, int_signed=True)
VOID = Type(kind=TypeKind.VOID)
# ...

def ptr_to(t: Type) -> Type:
    return Type(kind=TypeKind.PTR, subtype=t)

def array_of(t: Type, size: int) -> Type:
    return Type(kind=TypeKind.ARRAY, subtype=t, array_size=size)

def func_type(ret: Type, params: tuple[Type, ...]) -> Type:
    return Type(kind=TypeKind.FUNC, return_type=ret, param_types=params)
```

## 代码生成器的工作流

1. **创建 LLVM 上下文和模块**
   ```python
   self.context = LLVMContextCreate()
   self.module = LLVMModuleCreateWithNameInContext(b"xcc", self.context)
   ```

2. **声明全局变量和函数**（先声明，后定义）
   ```python
   for decl in translation_unit.decls:
       if isinstance(decl, FunctionDef):
           self._declare_function(decl)
       elif isinstance(decl, VarDecl):
           self._declare_global(decl)
   ```

3. **定义函数体**
   ```python
   for func_def in function_defs:
       self._define_function(func_def)
       # 内部：
       #   alloca 每个参数和局部变量
       #   遍历 CompoundStmt，逐个 emit 每个语句
       #   处理控制流：if → cond_br, while → loop + br, for → entry/test/body/inc loop
   ```

4. **输出 LLVM IR**
   ```python
   ir_text = LLVMPrintModuleToString(self.module)
   ```

## 已验证的能力

- 完整解析 CPython 的 442 个 .c 文件（预处理 + 词法分析 + 解析 + 语义分析）
- 432/442 文件通过原生 LLVM 后端编译
- C11 核心特性：函数定义、指针、数组、struct、enum、typedef、控制流、表达式
- GNU 扩展：`__attribute__`、`typeof`、语句表达式、复合字面量、K&R 定义

---

下一站：[学习路径](learning-path.md) — 如何从零开始学习编译器构建。
