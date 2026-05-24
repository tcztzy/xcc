# Semantic Analysis: Type Checking, Symbol Tables, and Constant Evaluation

Semantic analysis is the frontend's final step. It takes a bare AST and produces a **type-annotated AST**, answering: "Is this program legal at the type level?"

## What Semantic Analysis Does

1. **Symbol table management**: Build scopes, bind identifiers to declarations
2. **Type resolution**: Derive actual types from type specifiers + declarators
3. **Type checking**: Assignment compatibility, expression type inference, call argument matching
4. **Constant evaluation**: Evaluate compile-time integer constant expressions
5. **Implicit conversion insertion**: Integer promotion, arithmetic conversions, pointer conversions
6. **Record layout**: Compute `sizeof` and `alignof` for structs/unions

## Symbol Table

C has four "name spaces" — identifiers with the same name can coexist in different spaces:

| Name Space | Contents |
|------------|----------|
| Label | `goto` targets |
| Tag | `struct X`, `union Y`, `enum Z` names |
| Member | Member names within each struct/union |
| Ordinary | Variables, functions, typedefs, enum constants |

### XCC Symbol Table Implementation

XCC uses a **multi-level scope stack** (`src/xcc/sema/symbols.py`):

```python
@dataclass
class Scope:
    parent: Scope | None          # link to parent scope
    variables: dict[str, VarSymbol]
    functions: dict[str, FunctionSymbol]
    typedefs: dict[str, Type]     # typedef managed separately
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

Scopes are created when entering a new block (`{ ... }`) and destroyed after processing it. Identifier lookup starts from the innermost scope and traverses outward.

### TCC's Minimal Symbol Table

TCC uses a global stack (`sym_stack`) with `Sym` structs:

```c
typedef struct Sym {
    int v;           // token code or constant value
    int r;           // register or offset (used directly by codegen!)
    CType type;      // type
    struct Sym *next; // linked list to next symbol
} Sym;
```

**Key TCC design**: symbol table fields `v` and `r` directly store the registers and offsets needed for code generation. Semantic analysis and codegen are not separated — sema results ARE the codegen-ready state. This is the defining characteristic of single-pass compilation.

## Type System

C types are determined by two components: **type specifier** + **declarator**.

```
Type specifier:  int, long, unsigned, struct X, ...
Declarator:      *p, arr[10], fn(int, char), ...
Final type:      int *p → pointer to int
                 int arr[10] → array of 10 ints
                 int fn(int, char) → function(int, char) returning int
```

### XCC Type Representation

```python
@dataclass(frozen=True)
class Type:
    kind: TypeKind           # INT / PTR / ARRAY / FUNC / RECORD / VOID / ...
    modifiers: int            # bitmask: CONST | VOLATILE | RESTRICT
    # kind-specific:
    subtype: Type | None      # pointee type / array element type
    array_size: int | None    # array size (None = VLA or incomplete)
    param_types: tuple        # function parameter types
    return_type: Type | None  # function return type
```

### Type Systems Across Projects

| Project | Type Representation | Characteristics |
|---------|---------------------|-----------------|
| **GCC** | `tree` nodes, `INTEGER_TYPE` / `POINTER_TYPE` etc. | Extremely complex, encodes ABI details |
| **Clang** | `clang::QualType` + `clang::Type` hierarchy | Separated CV-qualifiers (const/volatile) |
| **TCC** | `CType` union | Minimal, `t` field encodes base type, `ref` points to modified type |
| **CCC** | Dual: `CType` (C semantics) + `IrType` (machine-level) | Former for type checking, latter for codegen |
| **XCC** | `Type` dataclass (`types.py`) | Modular, each kind has dedicated fields |

### TCC's Type Encoding Trick

TCC's `CType` achieves extreme space efficiency via a union:

```c
typedef struct CType {
    int t;               // base type: VT_INT, VT_PTR, VT_STRUCT, ...
    union {
        struct Sym *ref; // pointed-to type or struct definition
        long long i;     // constant (in constant expressions only)
    };
} CType;
```

Base type is encoded in the low bits of `t`, and modifier flags (`unsigned`, `const`, `volatile`, etc.) use high bits.

## Core Type Checking Algorithms

### 1. Integer Promotion

C rule: types narrower than `int` are automatically promoted to `int` before operations.

```c
char a = 1, b = 2;
int c = a + b;   // a and b promoted to int before addition
```

### 2. Usual Arithmetic Conversions

When binary operands have different types, these conversion rules apply:

```
long double ← double ← float ← unsigned long long ← long long
    ← unsigned long ← long ← unsigned int ← int
```

XCC implementation (`src/xcc/sema/type_helpers.py`) includes a complete integer rank system:

```python
def integer_rank(t: Type) -> int:
    # _Bool(1) < char(2) < short(3) < int(4) < long(5) < long long(6)

def usual_arithmetic_conversion(t1: Type, t2: Type) -> Type:
    # returns the common converted type
```

### 3. Implicit Conversion Insertion

When semantic analysis finds a type mismatch, it inserts implicit conversion nodes:

```python
@dataclass(frozen=True)
class ImplicitCast(Expr):
    """AST node: compiler-inserted implicit type conversion"""
    expr: Expr
    target_type: Type
    cast_kind: str    # "lvalue_to_rvalue" | "integral_promotion" | ...
```

This avoids the code generator having to figure out conversion logic itself. With explicit conversion annotations on the AST, the code generator simply mechanically translates each node.

## Semantic Analysis Scale

| Project | Sema code size | Capability |
|---------|---------------|------------|
| **GCC** | ~50000+ (C FE + common) | Most complete C semantics |
| **Clang** | ~15000 (Sema*.cpp) | Modern diagnostics included |
| **TCC** | ~9000 (`tccgen.c`) | Merged sema + codegen |
| **CCC** | ~3000 Rust | Type checking + const eval |
| **XCC** | ~3500 Python (`sema/`) | Full type system + implicit conversions + format checking |

---

Next: [IR Landscape](ir-landscape.md) — if the frontend "understands" the program, IR is the core of "transforming" it.
