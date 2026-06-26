# AOT Python Design

## Goal

Make XCC source remain ordinary Python 3.11+ while adding a path that compiles
the XCC-used Python subset directly to native code without the CPython runtime.
The final target is a native `xcc` built from this repository's Python source
that can compile this repository itself. The path must not introduce new Python
syntax, CPython-specific compiler shortcuts, non-stdlib runtime dependencies, or
Cython-style marker decorators.

The only permitted source-level additions are ordinary Python type annotations
or aliases that also run under CPython. Width-specific aliases such as `int64`,
`uint32`, and `usize` may exist as Python-visible aliases, for example aliases
to `int`, while the AOT checker interprets them as machine-width constraints.

## Current Constraints

- Runtime source remains Python standard-library only.
- Source must support CPython 3.11+.
- `from __future__ import annotations` remains forbidden.
- GPL-derived sources and tests remain forbidden.
- LLVM IR output is lowered through `/opt/homebrew/opt/llvm/bin/llc`.
- Existing `xcc` CLI behavior and pure-Python tests remain authoritative.
- Existing C compiler specs and target specs remain separate from this AOT
  Python track.
- The project currently enforces a 100% coverage gate, so AOT work must land in
  narrow, fully tested slices.

## Non-Goals

- Reimplementing the full CPython runtime or object model.
- Accepting arbitrary Python packages.
- Supporting Python reflection as a compilation contract.
- Depending on Cython, mypyc, Nuitka, LLVM Python bindings, or non-stdlib
  runtime packages for the produced compiler.
- Adding syntax, decorators, pragmas, comments-as-directives, or source
  transforms that make the Python source stop looking like normal Python.
- Making CPython-specific build or source-path exceptions.

## Approach

Add an independent `xcc.aot` track that consumes ordinary `.py` files and
produces native code for a documented XCC-Python subset. The existing Python
implementation remains the reference implementation and the development
fallback.

The compiler pipeline is:

```text
Python source
  -> CPython ast.parse
  -> XCC-Python subset checker
  -> type binder
  -> AOT IR
  -> textual LLVM IR
  -> /opt/homebrew/opt/llvm/bin/llc
  -> object/native executable
```

The first implementation slice compiles core modules that exercise the needed
language model without immediately requiring OS process control, filesystem
abstractions, or LLVM-C dynamic loading:

- `src/xcc/types.py`
- `src/xcc/diag.py`
- `src/xcc/options.py`
- `src/xcc/ast.py`
- `src/xcc/lexer.py`

This slice proves dataclass layout, normal functions, methods, inheritance tags,
`isinstance`, strings, bounded containers, and explicit error paths. Later slices
grow through parser, sema, and backend modules until a native `xcc` can compile
the repository.

## XCC-Python Subset

The accepted syntax is a strict CPython subset:

- modules, imports from the XCC package and approved stdlib shims
- `class` definitions with ordinary inheritance
- `@dataclass` and `@dataclass(frozen=True)` only as normal existing Python
  decorators with AOT-recognized semantics
- `def`, positional parameters, keyword-only defaults when statically known,
  and explicit returns
- assignment, annotated assignment, tuple unpacking when arity is static
- `if`, `while`, `for` over known iterable categories, `break`, `continue`
- `try`/`except` in forms lowerable to explicit error paths
- `raise` of supported exception classes
- `assert` as a checked trap in debug builds or a required proof in release
  builds
- list, tuple, dict, set literals with statically known element categories
- bounded list, dict, set, and generator comprehensions when their lowering is
  equivalent to an accepted loop
- calls to functions and methods with statically resolved targets
- `is`, `is not`, `in`, `not in`, equality, ordering, arithmetic, bitwise, and
  boolean operations over supported types
- `isinstance(value, Class)` and `isinstance(value, (ClassA, ClassB))`
- string slicing, indexing, comparison, concatenation, `startswith`, `endswith`,
  `join`, `split`, `strip`, `replace`, and related operations as admitted by
  the runtime contract

The rejected features are also part of the contract:

- `eval`, `exec`, dynamic import, runtime import hooks
- arbitrary `getattr`, `setattr`, `hasattr`, `delattr`, or `globals`/`locals`
  driven reflection
- monkeypatching functions, classes, or module globals after initialization
- metaclasses, custom descriptors, dynamic `__getattr__`, and dynamic
  `__getattribute__`
- generators that escape their lowering scope
- coroutines, `async`, `await`, and `yield`
- runtime mutation of class layout
- dependence on object identity except for `None`, booleans, interned type tags,
  and explicitly documented singleton values
- arbitrary stdlib object escape across the AOT boundary

Rejected constructs fail in the subset checker with deterministic diagnostics
that include file, line, column when available, and a stable diagnostic code.

## Type Model

Existing annotations are the starting point. AOT does not require the whole
repository to become fully annotated before the first slice lands.

The binder uses these rules:

- Function ABI boundaries must have explicit annotations or a complete inferred
  signature from dataclass fields and local call graph facts.
- Dataclass fields define fixed object layout.
- Local variables may be inferred from literals, constructor calls, container
  literals, branches, and assignments when a single static type is proven.
- `None` uses option types only when the annotation or control flow proves that
  a value can be absent.
- Union syntax is accepted only when every arm is supported and dispatch is
  statically representable.
- `typing.cast` is compile-time only and emits a checked assertion unless the
  checker can prove the cast.
- Width aliases such as `int64` and `uint32` lower to fixed-width integer IR
  types. Plain `int` keeps Python-compatible unbounded semantics where required
  by the slice, and may lower to tagged or boxed integer runtime operations.

The first slice should avoid broad integer semantic changes in existing source.
Width aliases are added only where native ABI, object layout, or LLVM lowering
needs an exact width.

## Runtime Model

The AOT runtime is deliberately smaller than CPython. It implements only the
behavior needed by XCC's own accepted subset.

Core runtime objects:

- object header with type tag
- fixed-layout dataclass records
- optional arena allocation for first slices
- UTF-8 string object
- dynamic array for accepted `list` operations
- immutable tuple object
- hash map for accepted `dict` and `set` operations
- explicit error object or error code for lowered exceptions

The first runtime uses arena lifetime for compiler-internal work products. It
does not need general CPython-compatible reference counting or cycle collection.
If Milestone 5 or Milestone 6 fixtures require longer-lived shared objects, the
runtime can add reference counts at object boundaries without changing accepted
source syntax.

`isinstance` lowers to type-tag tests. Inheritance is encoded as static type-tag
ranges or parent links. Frozen dataclasses lower to fixed records whose fields
cannot be assigned outside the generated initializer and recognized
`__post_init__` normalization path.

Exceptions lower to explicit error-return control flow. The AOT ABI represents
fallible functions as either a result union or an out-parameter plus status code.
The Python source still uses `raise`, `try`, and `except`; only the lowering
changes.

## Standard Library Boundary

The AOT track should treat stdlib use as a set of small owned shims, not as a
promise to compile the whole standard library.

Initial shim categories:

- `dataclasses`: recognized at compile time for field layout and generated
  initializer semantics
- `typing`: erased except for accepted type facts such as `Literal`, `cast`,
  and aliases
- `enum`: lowered for simple `Enum`/`auto` patterns used by `lexer.py`
- `re`: not compiled as general regex in the first slice; Milestone 4 either
  keeps lexer patterns as admitted constant-pattern shims or replaces them with
  hand-written scanners that preserve CPython behavior
- `pathlib`, `subprocess`, `argparse`, `json`, `ctypes`: outside the first
  slice and admitted in Milestone 5 or Milestone 6 only through explicit shims
  or boundary APIs

Any stdlib feature not listed in the active slice is rejected with a diagnostic
instead of silently falling back to CPython.

## Components

### Subset Checker

Responsible for parsing modules with `ast.parse`, resolving imports within the
compile set, and rejecting unsupported syntax or dynamic behavior. It produces a
module summary containing declarations, class layout candidates, function
signatures, imports, and diagnostics.

### Type Binder

Responsible for resolving annotations, width aliases, dataclass fields, local
variable types, function signatures, and method receivers. It produces a typed
module graph. It must distinguish unsupported inference from unsupported syntax
so diagnostics tell the developer whether to add an annotation or change code.

### AOT IR

A small target-independent IR for Python-subset semantics. It should represent:

- modules and initialization order
- functions and methods
- fixed records and type tags
- primitive values, boxed values, strings, arrays, maps, and option values
- structured control flow
- explicit error-return paths

This IR is not the existing C AST. Reusing the C AST would conflate C semantics
with Python-subset semantics and make Milestone 6 self-hosting harder to reason
about.

### LLVM Emitter

Responsible for lowering AOT IR to textual LLVM IR. Textual IR keeps the first
slice independent from Python `ctypes` and the existing `src/xcc/llvm_api.py`
dynamic libLLVM-C binding. Object output is produced by invoking the configured
`llc` path.

### Test Harness

Responsible for running CPython and native outputs on the same cases and
comparing observable behavior. It owns fixture compilation, executable launch,
stdout/stderr capture, return codes, and deterministic failure messages.

## Data Flow

For each testable exported function in a slice:

1. Run the Python implementation under CPython with a supported input fixture.
2. Compile the containing module graph through `xcc.aot`.
3. Link the generated runtime support and emitted object code into a test
   executable.
4. Run the native executable with the same fixture.
5. Compare return value, string output, or explicit error result.

For module initialization:

1. Resolve imports within the compile set.
2. Initialize constants and dataclass type descriptors in dependency order.
3. Reject module top-level side effects outside the accepted subset.

## Error Handling

The checker emits deterministic diagnostics for:

- unsupported syntax
- unsupported stdlib call
- missing or ambiguous type
- unsupported dynamic dispatch
- unsupported container operation
- unsupported exception shape
- LLVM lowering invariant violation

Runtime errors use explicit status codes or error objects. Tests compare these
against the CPython reference where the CPython path raises the corresponding
exception. The AOT path does not need byte-for-byte CPython traceback output.

## Testing Strategy

Every AOT feature lands with two categories of tests:

- checker tests that accept and reject small source snippets with exact
  diagnostics
- oracle tests that compare CPython behavior against native behavior

The first slice should include:

- fixed-width alias recognition tests
- dataclass layout and frozen field tests
- `Type.__str__`, `pointer_to`, `pointee`, `array_of`, `element_type`,
  `function_of`, and `callable_signature` oracle tests
- `Diagnostic.__str__` and exception-shape oracle tests
- `FrontendOptions.__post_init__` validation oracle tests
- lexer scanner tests for token output and selected error paths

Handoff for code changes still requires:

```text
uv run tox -e lint
uv run tox -e type
```

Design-only commits do not prove implementation completion. AOT implementation
tasks must also run focused AOT tests and the relevant existing Python tests.

## Milestones

### Milestone 1: Checker and Type Binder Skeleton

Create `xcc.aot` modules for parsing, subset checking, diagnostics, and type
binding. Validate accepted and rejected snippets without emitting native code.

### Milestone 2: Scalar and Dataclass Native Smoke

Emit textual LLVM IR for simple functions, fixed dataclass records, methods,
string returns, and explicit error-return cases. Lower through `llc` and compare
native output with CPython fixtures.

### Milestone 3: Core Module Slice

Compile and validate `types.py`, `diag.py`, and `options.py` functions used by
the test harness. Add only necessary width aliases or annotations.

### Milestone 4: AST and Lexer Slice

Compile enough of `ast.py` and `lexer.py` to tokenize representative C source
fixtures through native code and compare token streams with CPython.

### Milestone 5: Parser and Sema Expansion

Admit the parser and semantic-analysis helper patterns needed by current XCC:
larger class graphs, more `isinstance` dispatch, nested containers, and explicit
error paths.

### Milestone 6: Native XCC Bootstrap

Compile a native `xcc` from the repository's accepted Python source, run the
existing frontend/compiler test suite through the native executable where
applicable, then use native `xcc` to compile the project inputs required for
self-hosting validation.

## Risks and Mitigations

- **Risk: object model grows into full CPython.** Keep each slice tied to XCC
  source patterns and reject unsupported behavior deterministically.
- **Risk: source annotations churn grows too large.** Permit local inference and
  add width aliases only where ABI or layout requires exact widths.
- **Risk: stdlib shims become hidden fallbacks.** Treat every shim as an
  explicit AOT-owned contract with tests; reject everything else.
- **Risk: tests compare too little.** Require CPython/native double-run tests
  for every emitted behavior, not just IR text checks.
- **Risk: native memory lifetime is wrong.** Start with arena allocation for
  compiler-phase values and add narrower ownership only when a concrete fixture
  proves the need.
- **Risk: backend paths duplicate the existing C compiler backend.** Keep AOT IR
  separate from C AST, but reuse LLVM text conventions and `llc` tool handling
  where the contracts match.

## Acceptance Criteria

The design is implemented only when all of these are true:

- XCC remains importable and runnable under CPython 3.11+ with no non-stdlib
  runtime dependencies.
- No new Python syntax, decorators, pragmas, or comment directives are required.
- The AOT checker documents and enforces the accepted Python subset.
- Width aliases are ordinary Python-visible names and do not alter CPython
  execution.
- The first core module slice compiles to native code and passes CPython/native
  oracle tests.
- Unsupported syntax and stdlib behavior fail with deterministic diagnostics.
- The final bootstrap milestone produces a native `xcc` that can compile this
  repository's required inputs without the CPython runtime.
- `uv run tox -e lint` and `uv run tox -e type` pass before handoff for code
  changes.
