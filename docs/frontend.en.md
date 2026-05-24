# Frontend: Preprocessor → Lexer → Parser

The frontend is the top layer of the compiler, responsible for converting C source text into an AST. All compilers share the same frontend stages, but differ in preprocessing strategy and parsing technique.

## 1. Preprocessor

The C preprocessor handles:
- **Macro definitions** (`#define`) and macro expansion
- **Header file inclusion** (`#include`)
- **Conditional compilation** (`#if` / `#ifdef` / `#ifndef`)
- **Line markers** (`#line`)
- **Pragma directives**

### Preprocessing Strategy Comparison

| Project | Strategy | Characteristics |
|---------|----------|-----------------|
| **GCC** | Standalone `libcpp` library | Generates token stream, not text; header guard detection |
| **Clang** | Integrated `clang::Preprocessor` | Tight lexer coupling, tracks macro expansion stack |
| **TCC** | `tccpp.c` (~4000 lines) | Expands and feeds directly to lexer, no intermediate buffer |
| **CCC** | Rust implementation | Text-to-text expansion with `# line "file"` markers |
| **XCC** | Python implementation (`preprocessor/`) | Complete independent preprocessor with macro re-entry detection |

### XCC Preprocessor Modules

```
preprocessor/
├── __init__.py           # _Preprocessor main class, macro table
├── text.py               # Text-mode tokenization, directive parsing
├── macros.py             # _Macro, _MacroToken data structures
├── macro_expansion.py    # Function-like and object-like macro expansion
├── expressions.py        # #if expression evaluation
├── conditionals.py       # #if/#ifdef/#endif conditional stack
├── includes.py           # #include path resolution (angle bracket / quoted)
├── probes.py             # __has_include, __has_feature probing macros
└── pragmas.py            # #pragma handling
```

Supports C11 + GNU + Apple/ARM64 platform predefined macros.

## 2. Lexer (Tokenizer)

The lexer converts a character stream into a token stream. Token granularity determines parser complexity.

### Token Types

Typical C tokens:
- **Keywords**: `int`, `return`, `if`, `while`, `struct`, etc.
- **Identifiers**: function names, variable names, typedef names
- **Literals**: integers `42`, floats `3.14`, characters `'a'`, strings `"hello"`
- **Operators/Delimiters**: `+`, `->`, `{`, `;`, etc.

### Implementation Comparison

| Project | Approach | Lines | Characteristics |
|---------|----------|-------|-----------------|
| **GCC** | Hand-written + libcpp | ~5000 | Multi-language C/C++/ObjC |
| **Clang** | Hand-written | ~8000 | `clang::Lexer`, precise source locations |
| **TCC** | Hand-written (inline in `tccpp.c`) | ~500 | Minimal, character-level state machine |
| **CCC** | Hand-written Rust | ~1500 | Span-annotated for error reporting |
| **XCC** | Hand-written Python (`lexer.py`) | ~800 | No regex, pure state machine, trigraph + line splicing support |

### XCC Lexer Design

```python
class TokenKind(enum.Enum):
    KEYWORD = "keyword"
    IDENT = "identifier"
    INT_CONST = "integer"
    FLOAT_CONST = "float"
    CHAR_CONST = "character"
    STRING_LITERAL = "string"
    PUNCTUATOR = "punctuator"  # + - * / ( ) { } ; etc.

@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    line: int
    col: int
```

### TCC's Minimal Lexer

TCC merges preprocessing and lexical analysis, using a compact `tok_str()` function:

```c
enum {
    TOK_EOF = -1,
    TOK_INT = 256,
    TOK_IF,
    TOK_WHILE,
    // ... keywords start from 0x100
};
```

## 3. Parser

The parser converts the token sequence into an **AST (Abstract Syntax Tree)**. C has two parsing challenges:
1. **Disambiguation**: `a * b` is multiplication or pointer declaration depending on whether `a` is a variable or typedef
2. **Complex declarations**: C's "declaration mimics use" syntax forces parsers to reconstruct type structure

### Parsing Techniques

| Technique | Used By | Pros | Cons |
|-----------|---------|------|------|
| **Recursive descent (hand-written)** | XCC, CCC, TCC | Easy to understand/debug, good errors | Manual left-recursion handling |
| **Recursive descent (table-driven)** | Clang | Flexible, extensible | Large codebase |
| **Yacc/Bison (LALR)** | GCC (historical) | Declarative | Hard error recovery, hard to debug |

All five projects use **hand-written recursive descent** — the mainstream choice for modern compilers.

### XCC Parser Structure

```
parser/
├── __init__.py          # Parser main class: recursive descent entry
├── model.py             # ParserError, DeclSpecInfo
├── expressions.py       # Expression parsing (precedence climbing)
├── statements.py        # Statement parsing
├── type_specs.py        # Type specifier parsing (int, struct, enum, typeof...)
├── declarators.py       # Declarator parsing (pointer, array, function types)
├── array_sizes.py       # Array size constant evaluation
├── extensions.py        # GNU/MSVC extensions
├── diagnostics.py       # Error messages
└── type_diagnostics.py  # Type error helpers
```

#### Precedence Climbing

XCC uses **precedence climbing** for expression parsing:

```
Operator precedence table (C operators, low to high):
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
  13 Prefix: ++, --, +, -, !, ~, *, &, sizeof, (type)
  14 Postfix: ++, --, [], (), ->, .
```

For `a + b * c`, precedence climbing ensures `*` (level 12) binds before `+` (level 11).

### AST Design Comparison

| Project | AST Representation | Memory Management |
|---------|-------------------|-------------------|
| **GCC** | `tree` (union + tag) | GC (Garbage Collection) |
| **Clang** | `Stmt` / `Expr` inheritance hierarchy | Smart pointers + Arena |
| **TCC** | **No explicit AST** — generates code during parse | Stack allocation |
| **CCC** | Span-annotated enum types | Rust ownership |
| **XCC** | `@dataclass(frozen=True)` Python classes | Python GC |

#### XCC AST Examples

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

All XCC AST nodes are `frozen=True` dataclasses — making them immutable, hashable, and preventing accidental mutation.

### Concrete Example: Parsing `int main(void) { return 42; }`

```
Tokenization:
  int → KEYWORD       main → IDENT        ( → LPAREN
  void → KEYWORD      ) → RPAREN          { → LBRACE
  return → KEYWORD    42 → INT_CONST      ; → SEMICOLON
  } → RBRACE

Generated AST:
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

Next: [Semantic Analysis](semantic-analysis.md) — injecting type information into the bare AST.
