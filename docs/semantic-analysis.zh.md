# 语义分析：类型检查、符号表与常量求值

语义分析是编译器前端最后一步。它接收裸 AST，输出**带类型标注的 AST**。这一步回答："这个程序在类型层面是否合法？"

## 语义分析做什么

1. **符号表管理**：建立作用域、绑定标识符到声明
2. **类型解析**：根据类型说明符 (type specifier) 和声明符 (declarator) 推导实际类型
3. **类型检查**：赋值兼容、运算类型推导、函数调用参数匹配
4. **常量求值**：在编译期计算可用 `constexpr` 的整数表达式
5. **隐式转换插入**：整数提升、算术转换、隐式指针转换
6. **记录布局**：计算 struct/union 的 `sizeof` 和 `alignof`

## 符号表 (Symbol Table)

C 有四类"名字空间"，同名标识符可以分别存在于不同空间：

| 名字空间 | 包含 |
|----------|------|
| 标签 (Label) | `goto` 的目标 |
| 标签名 (Tag) | `struct X`, `union Y`, `enum Z` 的名字 |
| 成员 (Member) | 每个 struct/union 内部的成员名 |
| 普通标识符 | 变量、函数、typedef、enum 常量 |

### XCC 的符号表实现

XCC 使用 **多级作用域栈**（`src/xcc/sema/symbols.py`）：

```python
@dataclass
class Scope:
    parent: Scope | None          # 链向父作用域
    variables: dict[str, VarSymbol]
    functions: dict[str, FunctionSymbol]
    typedefs: dict[str, Type]     # typedef 单独管理
    labels: dict[str, LabelSymbol]

@dataclass
class VarSymbol:
    name: str
    type: Type
    storage: StorageClass          # auto / static / extern / register

@dataclass
class FunctionSymbol:
    name: str
    return_type: Type
    param_types: tuple[Type, ...]
    is_variadic: bool
```

作用域在进入新 block (`{ ... }`) 时创建，处理完 block 后销毁。标识符查找从最内层作用域开始，逐级向外遍历。

### TCC 的极简符号表

TCC 用全局栈 (`sym_stack`) 管理符号，符号用 `Sym` 结构体：

```c
typedef struct Sym {
    int v;           // token 编码或常量值
    int r;           // 寄存器或偏移量（代码生成直接使用！）
    CType type;      // 类型
    struct Sym *next; // 链表指向下一个符号
    // ...
} Sym;
```

**TCC 的关键设计**：符号表的 `v` 和 `r` 字段直接存储代码生成所需的寄存器和偏移量。语义分析和代码生成不分离——语义分析的结果直接是可生成代码的状态。这是单遍编译器的核心特征。

## 类型系统

C 的类型由两部分决定：**类型说明符** + **声明符**。

```
类型说明符:  int, long, unsigned, struct X, ...
声明符:      *p, arr[10], fn(int, char), ...
最终类型:    int *p → pointer to int
            int arr[10] → array of 10 ints
            int fn(int, char) → function(int, char) returning int
```

### XCC 的类型表示

```python
@dataclass(frozen=True)
class Type:
    kind: TypeKind           # INT / PTR / ARRAY / FUNC / RECORD / VOID / ...
    modifiers: int            # bitmask: CONST | VOLATILE | RESTRICT
    # kind-specific:
    subtype: Type | None      # 指针指向的类型、数组元素类型
    array_size: int | None    # 数组长度（NULL 表示 VLA 或不完整数组）
    param_types: tuple        # 函数参数类型列表
    return_type: Type | None  # 函数返回类型
```

### 各项目的类型系统

| 项目 | 类型表示 | 特点 |
|------|----------|------|
| **GCC** | `tree` 节点，`INTEGER_TYPE` / `POINTER_TYPE` 等 | 非常复杂，编码了 ABI 细节 |
| **Clang** | `clang::QualType` + `clang::Type` 层次 | 分离的 CV-qualifier (const/volatile) |
| **TCC** | `CType` 联合体 | 极简，`t` 字段编码基础类型，`ref` 指向修饰类型 |
| **CCC** | 双重类型：`CType`(C 语义) + `IrType`(机器级) | 前者做类型检查，后者做代码生成 |
| **XCC** | `Type` dataclass (`types.py`) | 模块化，每种 kind 有专门字段 |

### TCC 的类型编码技巧

TCC 的 `CType` 用联合体实现了极致的空间效率：

```c
typedef struct CType {
    int t;               // 基础类型：VT_INT, VT_PTR, VT_STRUCT, ...
    union {
        struct Sym *ref; // 指针指向的类型，或 struct 定义
        long long i;     // 常量（仅在常量表达式中）
        // ...
    };
} CType;
```

基础类型编码在 `t` 字段的低位，修饰位（`unsigned`, `const`, `volatile` 等）用高位标志位存储。

## 类型检查核心算法

### 1. 整数提升 (Integer Promotion)

C 的规则：比 `int` 窄的整数类型在运算前自动提升为 `int`。

```c
char a = 1, b = 2;
int c = a + b;   // a 和 b 先提升为 int，再相加
```

### 2. 通常算术转换 (Usual Arithmetic Conversion)

二元运算时，两个操作数类型不一致时的转换规则：

```
long double ← double ← float ← unsigned long long ← long long
    ← unsigned long ← long ← unsigned int ← int
```

XCC 的实现 (`src/xcc/sema/type_helpers.py`) 包含完整的整数等级系统：

```python
def integer_rank(t: Type) -> int:
    # _Bool(1) < char(2) < short(3) < int(4) < long(5) < long long(6)
    ...

def usual_arithmetic_conversion(t1: Type, t2: Type) -> Type:
    # 返回两者转换后的共同类型
    ...
```

### 3. 隐式转换插入

当语义分析发现表达式类型与预期类型不符时，插入隐式转换节点：

```python
@dataclass(frozen=True)
class ImplicitCast(Expr):
    """AST 节点：表示编译期自动插入的类型转换"""
    expr: Expr
    target_type: Type
    cast_kind: str    # "lvalue_to_rvalue" | "integral_promotion" | ...
```

这避免了代码生成器自己判断转换逻辑。在 AST 上显式标注转换信息后，代码生成器只需机械地翻译每个节点。

## 各项目语义分析规模

| 项目 | 语义分析代码行数 | 功能 |
|------|------------------|------|
| **GCC** | ~50000+ (C FE + common) | 最完整的 C 语义实现 |
| **Clang** | ~15000 (Sema*.cpp) | 包含现代化诊断 |
| **TCC** | ~9000 (`tccgen.c`) | 合并语义分析 + 代码生成 |
| **CCC** | ~3000 Rust | 类型检查 + 常量求值 |
| **XCC** | ~3500 Python (`sema/`) | 完整类型系统 + 隐式转换 + 格式化检查 |

---

下一站：[IR 全景对比](ir-landscape.md) — 如果说前端是"理解程序"，那 IR 就是"转换程序"的核心。
