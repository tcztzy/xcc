# 前端：预处理器 → 词法分析 → 语法分析

前端是编译器最上层，负责将 C 源文本转化为 AST。所有编译器在前端的设计上大同小异，但在预处理策略和解析技术上各有特点。

## 1. 预处理器 (Preprocessor)

C 预处理器处理：
- **宏定义** (`#define`) 和宏展开
- **头文件包含** (`#include`)
- **条件编译** (`#if` / `#ifdef` / `#ifndef`)
- **行号标记** (`#line`)
- **pragma 指令**

### 预处理策略对比

| 项目 | 策略 | 特点 |
|------|------|------|
| **GCC** | 独立 `libcpp` 库 | 生成 token 流而非文本；宏展开、头文件保护一次完成 |
| **Clang** | 集成在 `clang::Preprocessor` | 与 Lexer 紧密耦合，可追踪宏展开栈 |
| **TCC** | `tccpp.c` (~4000 行) | 边展开边直接输送给词法分析器，无中间缓冲 |
| **CCC** | Rust 实现 | 文本到文本展开，输出带 `# line "file"` 标记的文本 |
| **XCC** | Python 实现 (`preprocessor/`) | 完整独立预处理模块，支持宏重入检测、`#if` 表达式求值 |

### XCC 预处理器亮点

XCC 的预处理器完全自实现（`src/xcc/preprocessor/`），模块分工清晰：

```
preprocessor/
├── __init__.py           # _Preprocessor 主类，定义宏表
├── text.py               # 文本模式 token 化、指令解析
├── macros.py             # _Macro, _MacroToken 数据结构
├── macro_expansion.py    # 函数宏/对象宏展开引擎
├── expressions.py        # #if 表达式求值
├── conditionals.py       # #if/#ifdef/#endif 条件栈
├── includes.py           # #include 路径解析（尖括号/双引号路径）
├── probes.py             # __has_include, __has_feature 等探测宏
└── pragmas.py            # #pragma 处理
```

支持 C11 + GNU + Apple/ARM64 平台的预定义宏。

## 2. 词法分析 (Lexer)

词法分析器将字符流转换为 Token 序列。Token 的粒度决定了解析器的复杂度。

### Token 类型

典型的 C Token 包括：
- **关键字**：`int`, `return`, `if`, `while`, `struct` 等
- **标识符**：函数名、变量名、typedef 名
- **字面量**：整数 `42`、浮点 `3.14`、字符 `'a'`、字符串 `"hello"`
- **运算符/分隔符**：`+`, `->`, `{`, `;` 等

### 实现方式对比

| 项目 | 方式 | 行数 | 特点 |
|------|------|------|------|
| **GCC** | 手写 + libcpp 宏展开 token 化 | ~5000 | 支持 C/C++/ObjC 多语言 |
| **Clang** | 手写 | ~8000 | `clang::Lexer`，精确 source location |
| **TCC** | 手写 (`tccpp.c` 内联) | ~500 | 极简，字符级状态机 |
| **CCC** | 手写 Rust | ~1500 | 带 Span 信息，用于错误报告 |
| **XCC** | 手写 Python (`lexer.py`) | ~800 | 无正则，纯状态机，支持三字符组替换和行拼接 |

### XCC Lexer 设计

```python
# Token 种类（简化示例）
class TokenKind(enum.Enum):
    KEYWORD = "keyword"
    IDENT = "identifier"
    INT_CONST = "integer"
    FLOAT_CONST = "float"
    CHAR_CONST = "character"
    STRING_LITERAL = "string"
    PUNCTUATOR = "punctuator"  # + - * / ( ) { } ; 等

# Token 数据结构
@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    line: int
    col: int
```

XCC 的 lexer 纯手写，不依赖正则表达式，在 Python 中实现了高效的状态机。支持 C11 翻译阶段 1-3（三字符组替换、行拼接）。

### TCC 的极简 Lexer

TCC 的 `tccpp.c` 将预处理和词法分析合并，用一个紧凑的 `tok_str()` 函数边读边切分 token：

```c
// TCC 的 token 类型枚举（简化）
enum {
    TOK_EOF = -1,
    TOK_INT = 256,   // 0x100
    TOK_IF,          // 0x101
    TOK_WHILE,       // 0x102
    // ... 关键字从 0x100 开始编号
};
```

## 3. 语法分析 (Parser)

语法分析器将 Token 序列转化为 **AST（抽象语法树）**。C 的语法有两个难点：
1. **歧义消除**：`a * b` 是乘法还是指针声明取决于 `a` 是变量还是 typedef
2. **声明语法复杂**：C 的声明方式 "声明模仿使用" 让解析器必须还原类型结构

### 解析技术

| 技术 | 使用项目 | 优点 | 缺点 |
|------|----------|------|------|
| **递归下降 (手写)** | XCC, CCC, TCC | 易理解、易调试、错误信息好 | 需手动处理左递归 |
| **递归下降 (表驱动)** | Clang | 灵活、可扩展 | 代码量大 |
| **Yacc/Bison (LALR)** | GCC 历史 | 声明式 | 错误恢复难、难调试 |

五个项目中，**全部使用手写递归下降**——这是现代编译器的主流选择。

### XCC Parser 结构

```
parser/
├── __init__.py          # Parser 主类：递归下降入口
├── model.py             # ParserError, DeclSpecInfo
├── expressions.py       # 表达式解析（优先级爬升算法）
├── statements.py        # 语句解析
├── type_specs.py        # 类型说明符解析（int, struct, enum, typeof...）
├── declarators.py       # 声明符解析（指针、数组、函数类型）
├── array_sizes.py       # 数组大小常量求值
├── extensions.py        # GNU/MSVC 扩展
├── diagnostics.py       # 错误信息
└── type_diagnostics.py  # 类型错误帮助
```

#### 表达式优先级爬升 (Precedence Climbing)

XCC 使用 **优先级爬升算法** 解析表达式：

```
优先级表（C 运算符，从低到高）：
  1  =, +=, -=, ...
  2  ?:
  3  ||
  4  &&
  5  |
  6  ^
  7  &
  8  ==, !=
  9  <, <=, >, >=
  10 <<, >>
  11 +, -
  12 *, /, %
  13 前缀: ++, --, +, -, !, ~, *, &, sizeof, (type)
  14 后缀: ++, --, [], (), ->, .
```

对于一个表达式 `a + b * c`，优先级爬升确保 `*`（优先级 12）先结合，再 `+`（优先级 11）。

### 各项目 AST 设计

| 项目 | AST 表示 | 内存管理 |
|------|----------|----------|
| **GCC** | `tree` (联合体 + tag) | GC (Garbage Collection) |
| **Clang** | `Stmt` / `Expr` 继承体系 | 智能指针 + Arena |
| **TCC** | **无显式 AST**——解析后直接生成代码 | 栈分配 |
| **CCC** | 带 Span 的枚举类型 | Rust 所有权 |
| **XCC** | `@dataclass(frozen=True)` Python 类 | Python GC |

#### XCC AST 示例

```python
@dataclass(frozen=True)
class FunctionDef:
    name: str
    return_type: TypeSpec
    params: tuple[ParamDecl, ...]
    body: CompoundStmt

@dataclass(frozen=True)  
class BinaryExpr:
    op: str            # "+" | "-" | "*" | ...
    left: Expr
    right: Expr

@dataclass(frozen=True)
class IfStmt:
    condition: Expr
    then_branch: Stmt
    else_branch: Stmt | None
```

XCC 的 AST 全部用 `frozen=True` 的 `dataclass` 实现——这让 AST 节点不可变、可哈希，防止意外修改。

### 一个具体示例：`int main(void) { return 42; }` 的解析过程

```
词法分析:
  int → KEYWORD       main → IDENT        ( → LPAREN
  void → KEYWORD      ) → RPAREN          { → LBRACE
  return → KEYWORD    42 → INT_CONST      ; → SEMICOLON
  } → RBRACE

语法分析生成 AST:
  TranslationUnit
  └── FunctionDef
      ├── name: "main"
      ├── return_type: TypeSpec("int")
      ├── params: [ParamDecl("void")]
      └── body: CompoundStmt
          └── ReturnStmt
              └── IntLiteral(42)
```

---

下一站：[语义分析](semantic-analysis.md) — 如何给这个裸 AST 注入类型信息。
