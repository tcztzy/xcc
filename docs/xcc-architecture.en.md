# XCC Architecture

XCC is a C11 compiler written in **pure Python**. It's the **most beginner-friendly** of the five projects — clean code, independent modules, no deep dependencies.

## Design Goals

1. **Python stdlib only**: Zero pip dependencies (LLVM-C dylib doesn't count as a Python package)
2. **Compile real C projects**: CPython is a flagship integration test, not a special case
3. **Target LLVM by default**: LLVM IR is treated as target assembly, then lowered by llc
4. **Educational**: Each stage is independently modularized, clear ast/sema/codegen separation

## Source Overview

```
src/xcc/                         (~21,000 lines Python, 41 files)
├── __init__.py              CLI entry point (main)
├── options.py               FrontendOptions dataclass
├── cc_driver.py             CC-compatible mode (-c, -S, -E, -o)
├── frontend.py              Frontend pipeline orchestrator
├── diag.py                  Diagnostics / error types
├── lexer.py                 Hand-written C11 lexer (~570 lines)
├── ast.py                   AST node definitions (~410 lines)
├── types.py                 Semantic type representation (~150 lines)
├── llvm_api.py              Raw libLLVM-C ctypes bindings (~700 lines)
├── codegen.py               AST → LLVM IR lowering (~4500 lines)
├── host_includes.py         macOS SDK header path detection
│
├── parser/                  Recursive-descent C11 parser (~4500 lines)
│   ├── __init__.py          Parser main class
│   ├── expressions.py       Expression parsing (precedence climbing)
│   ├── statements.py        Statement parsing
│   ├── type_specs.py        Type specifier parsing
│   ├── declarators.py       Declarator parsing
│   ├── array_sizes.py       Array size evaluation and diagnostics
│   └── extensions.py        GNU/MSVC extensions
│
├── sema/                    Semantic analysis (~5000 lines)
│   ├── __init__.py          Analyzer main class
│   ├── symbols.py           Symbol table / TypeMap / SemaUnit
│   ├── declarations.py      Declaration analysis
│   ├── statements.py        Statement type checking
│   ├── expressions.py       Expression type resolution
│   ├── type_resolution.py   TypeSpec → Type
│   ├── type_helpers.py      Integer ranks, promotions, arithmetic conversions
│   ├── conversions.py       Implicit conversion rules
│   ├── constants.py         Integer constant expression evaluation
│   ├── records.py           Record (struct/union) layout
│   ├── layout.py            sizeof / alignof computation
│   ├── initializers.py      Initializer list analysis
│   └── format_checking.py   Format string checking
│
└── preprocessor/            C preprocessor (~4200 lines)
    ├── __init__.py          _Preprocessor, errors, source locations
    ├── text.py              Directive parsing
    ├── macros.py            Macro definition structures
    ├── macro_expansion.py   Macro expansion engine
    ├── expressions.py       #if expression evaluation
    ├── conditionals.py      Conditional compilation stack
    ├── includes.py          #include path resolution
    ├── probes.py            __has_include etc.
    └── pragmas.py           #pragma handling
```

## Call Graph

```
                          __init__.py (CLI)
                               │
                    ┌──────────┼──────────┐
                    ▼                     ▼
              frontend.py           cc_driver.py
              (full pipeline)       (CC-compatible)
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
         codegen.py                     │
         (AST → LLVM IR lowering)      │
              │                         │
              ▼                         │
         llvm_api.py                    │
         (libLLVM-C ctypes)            │
              │                         │
              ▼                         ▼
         LLVM IR string
              │
              ▼
         llc (.s → .o)
              │
              ▼
         clang (link)
```

## Key Design Decisions

### 1. Frozen Dataclass AST

```python
@dataclass(frozen=True)
class BinaryExpr:
    op: str
    left: Expr
    right: Expr
```

`frozen=True` means AST nodes are immutable after creation. This prevents the parser or sema from accidentally mutating the AST, and makes nodes hashable (usable as dict keys, e.g., in `TypeMap` for node → type mapping).

### 2. Explicit Implicit Conversions

During semantic analysis, when a type mismatch is detected, the analyzer **inserts `ImplicitCast` nodes into the AST**:

```python
@dataclass(frozen=True)
class ImplicitCast(Expr):
    expr: Expr            # expression being converted
    target_type: Type     # target type
    cast_kind: str        # "lvalue_to_rvalue" | "integral_promotion" | ...
```

This avoids the code generator having to handle type conversion logic — it simply mechanically translates each node.

### 3. Target-Driven Codegen

XCC has target selection, not backend modes. The default target is `llvm`, so
normal compiler usage does not need an explicit target flag:

```python
# default target=llvm:
#   preprocessor → lex → parse → sema → LLVM IR → llc → clang

# explicit equivalent:
#   xcc --target=llvm -c file.c -o file.o

# -S writes the target assembly language.
# For target=llvm, that means textual LLVM IR.
```

### 4. Opaque Pointers

XCC uses LLVM 15+'s opaque pointer feature — all pointer types are unified as `ptr` (in LLVM-C API: `LLVMPointerType(i8, 0)`), no longer distinguishing `i32*` vs `i64*`. This simplifies type mapping and GEP operations.

### 5. Typed Helper-Module Contracts

Large parser, preprocessor, and sema helpers are kept in focused modules, but
their entry points use narrow `Protocol` contracts instead of untyped `Any`.
That keeps the main classes free to own state while making helper dependencies
visible to `ty check`.

### 6. Builtin Handling

XCC specially handles C standard `__builtin_*` functions:

```python
def _emit_builtin_call(self, name: str, args: list) -> LLVMValueRef | None:
    if name == "__builtin_memset":
        return LLVMBuildMemSet(self.builder, ptr, val, size, align)
    if name == "__builtin_memcpy":
        return LLVMBuildMemCpy(self.builder, dst, src, size, align)
    # ... direct mapping to LLVM intrinsic
    return None  # unrecognized builtin, treated as normal function call
```

## Type System

XCC's type system (`types.py`) uses a unified `Type` dataclass:

```python
@dataclass(frozen=True)
class Type:
    kind: TypeKind      # INT | PTR | ARRAY | FUNC | RECORD | VOID | ...
    modifiers: int      # bitmask: CONST | VOLATILE | RESTRICT
    # kind-specific fields:
    subtype: Type | None          # pointee type / array element type
    array_size: int | None        # array size
    param_types: tuple[Type, ...] # function parameter types
    return_type: Type | None      # function return type
    record_name: str | None       # struct/union name
    # integer type details:
    int_size: int                 # bit width (8, 16, 32, 64)
    int_signed: bool              # signedness
```

Predefined common type aliases:

```python
INT = Type(kind=TypeKind.INT, int_size=32, int_signed=True)
UINT = Type(kind=TypeKind.INT, int_size=32, int_signed=False)
LONG = Type(kind=TypeKind.INT, int_size=64, int_signed=True)
CHAR = Type(kind=TypeKind.INT, int_size=8, int_signed=True)
VOID = Type(kind=TypeKind.VOID)

def ptr_to(t: Type) -> Type:
    return Type(kind=TypeKind.PTR, subtype=t)

def array_of(t: Type, size: int) -> Type:
    return Type(kind=TypeKind.ARRAY, subtype=t, array_size=size)

def func_type(ret: Type, params: tuple[Type, ...]) -> Type:
    return Type(kind=TypeKind.FUNC, return_type=ret, param_types=params)
```

## Code Generator Workflow

1. **Create LLVM context and module**
   ```python
   self.context = LLVMContextCreate()
   self.module = LLVMModuleCreateWithNameInContext(b"xcc", self.context)
   ```

2. **Declare globals and functions** (declare first, define later)
   ```python
   for decl in translation_unit.decls:
       if isinstance(decl, FunctionDef):
           self._declare_function(decl)
       elif isinstance(decl, VarDecl):
           self._declare_global(decl)
   ```

3. **Define function bodies**
   ```python
   for func_def in function_defs:
       self._define_function(func_def)
       # Inside:
       #   alloca each parameter and local variable
       #   walk CompoundStmt, emit each statement
       #   handle control flow: if→cond_br, while→loop+br, for→entry/test/body/inc
   ```

4. **Output LLVM IR**
   ```python
   ir_text = LLVMPrintModuleToString(self.module)
   ```

## Verified Capabilities

- Full parse of CPython's 442 .c files (preprocessor + lex + parse + sema)
- 432/442 files compile through native LLVM backend
- C11 core features: function definitions, pointers, arrays, struct, enum, typedef, control flow, expressions
- GNU extensions: `__attribute__`, `typeof`, statement expressions, compound literals, K&R definitions

---

Next: [Learning Path](learning-path.md) — how to learn compiler construction from scratch.
