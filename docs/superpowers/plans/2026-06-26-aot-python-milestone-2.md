# AOT Python Milestone 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Milestone 2 native smoke path: lower a small typed XCC-Python subset to AOT IR, emit textual LLVM IR, compile it with `llc`, and compare native smoke fixtures with CPython.

**Architecture:** Keep the existing Milestone 1 parser, subset checker, and type binder as the front end. Add focused `xcc.aot` modules for IR modeling, Python-AST-to-IR lowering, textual LLVM emission, and native smoke execution; do not change the existing `xcc` C compiler CLI path.

**Tech Stack:** Python 3.11+ standard library, `ast`, `dataclasses`, `pathlib`, `subprocess`, `tempfile`, textual LLVM IR, `/opt/homebrew/opt/llvm/bin/llc` or `XCC_LLC`, existing `tox` gates.

---

## Scope Check

The approved design covers several milestones through full native bootstrap.
This plan covers only Milestone 2 from
`/Users/tcztzy/GitHub/xcc/docs/superpowers/specs/2026-06-26-aot-python-design.md`:

- lower simple scalar functions to AOT IR
- lower fixed frozen dataclass records, field reads, and methods used by smoke
  fixtures
- lower string-return smoke functions through a native wrapper that prints the
  string
- lower explicit error-return smoke functions as integer status results
- emit textual LLVM IR without using Python LLVM bindings
- invoke `llc` to generate an object file and link a small executable for oracle
  tests
- compare CPython fixture results with native executable results

This plan does not compile repository core modules such as `src/xcc/types.py`.
That is Milestone 3.

## File Structure

- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/ir.py`  
  Immutable AOT IR dataclasses for values, statements, functions, records, and
  modules.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/lower.py`  
  AST-to-AOT-IR lowering for Milestone 2 smoke fixtures.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/llvm_text.py`  
  Textual LLVM IR emitter for scalar values, records, methods, string constants,
  and smoke `main` wrappers.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/native.py`  
  CPython/native oracle harness and `llc` object compilation helper.
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`  
  Export new Milestone 2 public APIs.
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot_ir.py`  
  Unit tests for IR modeling and lowering.
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot_llvm.py`  
  Unit tests for LLVM text emission.
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot_native.py`  
  Mocked native harness tests plus optional real `llc` smoke tests when the
  toolchain is present.
- Modify: `/Users/tcztzy/GitHub/xcc/CHANGELOG.md`  
  Record Milestone 2 after implementation passes.

## Diagnostic Codes

Use these exact new codes in Milestone 2:

- `XCC-AOT-LOWER-0001`: unsupported lowering syntax or statement.
- `XCC-AOT-LOWER-0002`: unsupported expression form.
- `XCC-AOT-LOWER-0003`: unsupported call target.
- `XCC-AOT-LLVM-0001`: unsupported IR node for LLVM emission.
- `XCC-AOT-NATIVE-0001`: native toolchain command failed.

## Task 1: AOT IR Model

**Files:**
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/ir.py`
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot_ir.py`

- [ ] **Step 1: Write failing IR dataclass tests**

Create `/Users/tcztzy/GitHub/xcc/tests/test_aot_ir.py`:

```python
import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    IrAssign,
    IrBinary,
    IrConstInt,
    IrFunction,
    IrIntType,
    IrModule,
    IrParam,
    IrReturn,
)


class AotIrModelTests(unittest.TestCase):
    def test_ir_module_tracks_records_functions_and_entry(self) -> None:
        int64 = IrIntType(64, signed=True)
        function = IrFunction(
            "answer",
            (),
            int64,
            (IrReturn(IrConstInt(42, int64)),),
        )
        module = IrModule("sample.py", (), (function,), entry="answer")
        self.assertEqual(module.filename, "sample.py")
        self.assertEqual(module.records, ())
        self.assertEqual(module.functions, (function,))
        self.assertEqual(module.entry, "answer")

    def test_ir_statement_values_are_immutable(self) -> None:
        int64 = IrIntType(64, signed=True)
        statement = IrAssign(
            "total",
            IrBinary("+", IrConstInt(1, int64), IrConstInt(2, int64), int64),
        )
        with self.assertRaises(Exception):
            statement.target = "other"  # type: ignore[misc]

    def test_function_parameter_shape_is_explicit(self) -> None:
        int64 = IrIntType(64, signed=True)
        function = IrFunction(
            "identity",
            (IrParam("value", int64),),
            int64,
            (IrReturn(IrConstInt(0, int64)),),
        )
        self.assertEqual(function.params[0].name, "value")
        self.assertEqual(function.params[0].type, int64)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run IR tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_ir.AotIrModelTests -v
```

Expected: import failure for `IrAssign` or `xcc.aot.ir`.

- [ ] **Step 3: Implement the IR model**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/ir.py`:

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class IrIntType:
    bits: int
    signed: bool


@dataclass(frozen=True)
class IrStringType:
    pass


@dataclass(frozen=True)
class IrRecordType:
    name: str


IrType = IrIntType | IrStringType | IrRecordType


@dataclass(frozen=True)
class IrParam:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrField:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrRecord:
    name: str
    fields: tuple[IrField, ...]


@dataclass(frozen=True)
class IrConstInt:
    value: int
    type: IrIntType


@dataclass(frozen=True)
class IrConstString:
    value: str


@dataclass(frozen=True)
class IrName:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrBinary:
    op: Literal["+", "-", "*"]
    left: "IrExpr"
    right: "IrExpr"
    type: IrType


@dataclass(frozen=True)
class IrGetField:
    value: "IrExpr"
    field: str
    type: IrType


@dataclass(frozen=True)
class IrConstructRecord:
    record: str
    args: tuple["IrExpr", ...]
    type: IrRecordType


@dataclass(frozen=True)
class IrCall:
    target: str
    args: tuple["IrExpr", ...]
    type: IrType


IrExpr = IrConstInt | IrConstString | IrName | IrBinary | IrGetField | IrConstructRecord | IrCall


@dataclass(frozen=True)
class IrAssign:
    target: str
    value: IrExpr


@dataclass(frozen=True)
class IrReturn:
    value: IrExpr


IrStmt = IrAssign | IrReturn


@dataclass(frozen=True)
class IrFunction:
    name: str
    params: tuple[IrParam, ...]
    return_type: IrType
    body: tuple[IrStmt, ...]


@dataclass(frozen=True)
class IrModule:
    filename: str
    records: tuple[IrRecord, ...]
    functions: tuple[IrFunction, ...]
    entry: str | None = None
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py` by importing and
exporting all `Ir*` names from `xcc.aot.ir`.

- [ ] **Step 4: Run IR tests**

Run:

```bash
uv run python -m unittest tests.test_aot_ir.AotIrModelTests -v
```

Expected: all `AotIrModelTests` tests pass.

- [ ] **Step 5: Commit IR model**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/ir.py tests/test_aot_ir.py
git commit -m "feat: add AOT IR model"
```

## Task 2: Scalar Lowering

**Files:**
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/lower.py`
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Modify: `/Users/tcztzy/GitHub/xcc/tests/test_aot_ir.py`

- [ ] **Step 1: Add failing scalar lowering tests**

Append this class to `/Users/tcztzy/GitHub/xcc/tests/test_aot_ir.py` before the
`if __name__ == "__main__"` block:

```python
from xcc.aot import AotError, IrBinary, IrName, lower_source_to_ir


class AotScalarLoweringTests(unittest.TestCase):
    def test_lowers_int64_return_constant(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            filename="scalar.py",
            entry="answer",
        )
        function = module.functions[0]
        self.assertEqual(function.name, "answer")
        self.assertEqual(function.return_type.bits, 64)
        self.assertEqual(function.body[0].value.value, 42)

    def test_lowers_parameter_binary_return(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef add(left: int64, right: int64) -> int64:\n    return left + right\n",
            filename="add.py",
            entry="add",
        )
        function = module.functions[0]
        self.assertEqual([param.name for param in function.params], ["left", "right"])
        returned = function.body[0].value
        self.assertIsInstance(returned, IrBinary)
        self.assertEqual(returned.op, "+")
        self.assertEqual(returned.left, IrName("left", function.params[0].type))

    def test_rejects_unsupported_expression(self) -> None:
        with self.assertRaises(AotError) as ctx:
            lower_source_to_ir(
                "int64 = int\ndef f() -> int64:\n    return -1\n",
                filename="bad.py",
                entry="f",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")
```

- [ ] **Step 2: Run scalar lowering tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_ir.AotScalarLoweringTests -v
```

Expected: import failure for `lower_source_to_ir`.

- [ ] **Step 3: Implement scalar lowering**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/lower.py` with:

```python
import ast

from xcc.aot.analysis import analyze_source
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrBinary,
    IrConstInt,
    IrConstString,
    IrExpr,
    IrFunction,
    IrIntType,
    IrModule,
    IrName,
    IrParam,
    IrReturn,
    IrStmt,
    IrStringType,
    IrType,
)
from xcc.aot.types import AotType


def lower_source_to_ir(source: str, *, filename: str = "<input>", entry: str | None = None) -> IrModule:
    analysis = analyze_source(source, filename=filename)
    lowerer = _Lowerer(filename, analysis.types.functions)
    functions = tuple(lowerer.lower_function(node) for node in analysis.module.tree.body if isinstance(node, ast.FunctionDef))
    return IrModule(filename, (), functions, entry=entry)


class _Lowerer:
    def __init__(self, filename: str, function_types: dict[str, object]) -> None:
        self.filename = filename
        self.function_types = function_types

    def lower_function(self, node: ast.FunctionDef) -> IrFunction:
        params: list[IrParam] = []
        names: dict[str, IrType] = {}
        for arg in node.args.posonlyargs + node.args.args:
            if arg.annotation is None:
                self._error("XCC-AOT-LOWER-0001", f"Missing lowered parameter annotation: {node.name}.{arg.arg}", arg)
            ir_type = self._annotation_to_ir_type(arg.annotation)
            params.append(IrParam(arg.arg, ir_type))
            names[arg.arg] = ir_type
        return_type = self._annotation_to_ir_type(node.returns)
        body = tuple(self._lower_statement(statement, names, return_type) for statement in node.body)
        return IrFunction(node.name, tuple(params), return_type, body)

    def _lower_statement(self, statement: ast.stmt, names: dict[str, IrType], return_type: IrType) -> IrStmt:
        if isinstance(statement, ast.Return) and statement.value is not None:
            return IrReturn(self._lower_expr(statement.value, names, return_type))
        self._error("XCC-AOT-LOWER-0001", f"Unsupported lowered statement: {type(statement).__name__}", statement)

    def _lower_expr(self, expr: ast.expr, names: dict[str, IrType], expected: IrType) -> IrExpr:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, int):
                if isinstance(expected, IrIntType):
                    return IrConstInt(expr.value, expected)
            if isinstance(expr.value, str):
                return IrConstString(expr.value)
        if isinstance(expr, ast.Name):
            value_type = names.get(expr.id)
            if value_type is None:
                self._error("XCC-AOT-LOWER-0002", f"Unknown lowered name: {expr.id}", expr)
            return IrName(expr.id, value_type)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add | ast.Sub | ast.Mult):
            op = "+" if isinstance(expr.op, ast.Add) else "-" if isinstance(expr.op, ast.Sub) else "*"
            return IrBinary(op, self._lower_expr(expr.left, names, expected), self._lower_expr(expr.right, names, expected), expected)
        self._error("XCC-AOT-LOWER-0002", f"Unsupported lowered expression: {type(expr).__name__}", expr)

    def _annotation_to_ir_type(self, annotation: ast.expr | None) -> IrType:
        if annotation is None:
            self._error("XCC-AOT-LOWER-0001", "Missing lowered annotation", ast.Pass())
        if isinstance(annotation, ast.Name):
            name = annotation.id
            if name == "str":
                return IrStringType()
            if name == "int":
                return IrIntType(64, signed=True)
            aot_type = AotType(name)
            if aot_type.name.startswith("uint"):
                return IrIntType(int(aot_type.name[4:]), signed=False)
            if aot_type.name.startswith("int"):
                return IrIntType(int(aot_type.name[3:]), signed=True)
        self._error("XCC-AOT-LOWER-0002", f"Unsupported lowered annotation: {ast.unparse(annotation)}", annotation)

    def _error(self, code: str, message: str, node: ast.AST) -> None:
        raise AotError(
            (
                AotDiagnostic(
                    code,
                    message,
                    filename=self.filename,
                    line=getattr(node, "lineno", None),
                    column=getattr(node, "col_offset", None),
                ),
            )
        )
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py` to export
`lower_source_to_ir`.

- [ ] **Step 4: Run scalar lowering tests**

Run:

```bash
uv run python -m unittest tests.test_aot_ir.AotScalarLoweringTests -v
```

Expected: all scalar lowering tests pass.

- [ ] **Step 5: Commit scalar lowering**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/lower.py tests/test_aot_ir.py
git commit -m "feat: lower scalar AOT Python to IR"
```

## Task 3: Dataclass Record and Method Lowering

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/lower.py`
- Modify: `/Users/tcztzy/GitHub/xcc/tests/test_aot_ir.py`

- [ ] **Step 1: Add failing dataclass and method lowering tests**

Append these tests to `AotScalarLoweringTests`:

```python
    def test_lowers_dataclass_record_layout_and_field_read(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "def use(pair: Pair) -> int64:\n"
            "    return pair.left + pair.right\n"
        )
        module = lower_source_to_ir(source, filename="pair.py", entry="use")
        self.assertEqual(module.records[0].name, "Pair")
        self.assertEqual([field.name for field in module.records[0].fields], ["left", "right"])
        returned = module.functions[0].body[0].value
        self.assertEqual(returned.left.field, "left")
        self.assertEqual(returned.right.field, "right")

    def test_lowers_record_constructor_and_method_call(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "    def total(self) -> int64:\n"
            "        return self.left + self.right\n"
            "def entry() -> int64:\n"
            "    pair = Pair(2, 3)\n"
            "    return pair.total()\n"
        )
        module = lower_source_to_ir(source, filename="method.py", entry="entry")
        self.assertEqual([function.name for function in module.functions], ["Pair.total", "entry"])
        self.assertEqual(module.functions[1].body[0].target, "pair")
        self.assertEqual(module.functions[1].body[1].value.target, "Pair.total")
```

- [ ] **Step 2: Run dataclass lowering tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_ir.AotScalarLoweringTests -v
```

Expected: failures in dataclass/method tests because records, assignments,
field access, constructors, and method calls are not lowered yet.

- [ ] **Step 3: Extend lowering for records, methods, assignments, attributes, and calls**

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/lower.py`:

```python
# Add these imports from xcc.aot.ir:
IrAssign,
IrCall,
IrConstructRecord,
IrField,
IrGetField,
IrRecord,
IrRecordType,

# Change lower_source_to_ir to:
analysis = analyze_source(source, filename=filename)
lowerer = _Lowerer(filename, analysis.types.functions, analysis.types.classes)
records = tuple(lowerer.lower_record(node) for node in analysis.module.tree.body if isinstance(node, ast.ClassDef))
functions = tuple(lowerer.lower_method_or_function(node, owner=None) for node in analysis.module.tree.body if isinstance(node, ast.FunctionDef))
for node in analysis.module.tree.body:
    if isinstance(node, ast.ClassDef):
        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                functions += (lowerer.lower_method_or_function(child, owner=node.name),)
return IrModule(filename, records, functions, entry=entry)

# Add methods:
def lower_record(self, node: ast.ClassDef) -> IrRecord:
    info = self.class_types[node.name]
    fields = tuple(IrField(name, self._aot_type_to_ir_type(field_type)) for name, field_type in info.fields.items())
    return IrRecord(node.name, fields)

def lower_method_or_function(self, node: ast.FunctionDef, owner: str | None) -> IrFunction:
    name = f"{owner}.{node.name}" if owner is not None else node.name
    params, names = self._lower_params(node, owner)
    return_type = self._annotation_to_ir_type(node.returns)
    body: list[IrStmt] = []
    for statement in node.body:
        body.append(self._lower_statement(statement, names, return_type))
    return IrFunction(name, tuple(params), return_type, tuple(body))

# Extend _lower_statement:
if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
    value = self._lower_expr(statement.value, names, return_type)
    names[statement.targets[0].id] = value.type
    return IrAssign(statement.targets[0].id, value)

# Extend _lower_expr:
if isinstance(expr, ast.Attribute):
    value = self._lower_expr(expr.value, names, expected)
    field_type = self._record_field_type(value.type, expr.attr, expr)
    return IrGetField(value, expr.attr, field_type)
if isinstance(expr, ast.Call):
    if isinstance(expr.func, ast.Name) and expr.func.id in self.class_types:
        record_type = IrRecordType(expr.func.id)
        return IrConstructRecord(expr.func.id, tuple(self._lower_expr(arg, names, expected) for arg in expr.args), record_type)
    if isinstance(expr.func, ast.Attribute):
        receiver = self._lower_expr(expr.func.value, names, expected)
        if isinstance(receiver.type, IrRecordType):
            target = f"{receiver.type.name}.{expr.func.attr}"
            args = (receiver,) + tuple(self._lower_expr(arg, names, expected) for arg in expr.args)
            return IrCall(target, args, expected)
    self._error("XCC-AOT-LOWER-0003", f"Unsupported call target: {ast.unparse(expr.func)}", expr)
```

Keep helper methods small:

```python
def _aot_type_to_ir_type(self, type_info: AotType) -> IrType:
    if type_info.bits is not None and type_info.signed is not None:
        return IrIntType(type_info.bits, type_info.signed)
    if type_info.name == "str":
        return IrStringType()
    if type_info.name in self.class_types:
        return IrRecordType(type_info.name)
    if type_info.name == "int":
        return IrIntType(64, signed=True)
    self._error("XCC-AOT-LOWER-0002", f"Unsupported lowered type: {type_info.name}", ast.Pass())
```

- [ ] **Step 4: Run AOT IR tests**

Run:

```bash
uv run python -m unittest tests.test_aot_ir -v
```

Expected: all IR and lowering tests pass.

- [ ] **Step 5: Commit dataclass and method lowering**

Run:

```bash
git add src/xcc/aot/lower.py tests/test_aot_ir.py
git commit -m "feat: lower dataclass smoke fixtures to IR"
```

## Task 4: Textual LLVM IR Emitter

**Files:**
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/llvm_text.py`
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot_llvm.py`

- [ ] **Step 1: Write failing LLVM text tests**

Create `/Users/tcztzy/GitHub/xcc/tests/test_aot_llvm.py`:

```python
import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import emit_llvm_text, lower_source_to_ir


class AotLlvmTextTests(unittest.TestCase):
    def test_emits_int64_function_and_main_wrapper(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            filename="scalar.py",
            entry="answer",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i64 @answer()", llvm_ir)
        self.assertIn("ret i64 42", llvm_ir)
        self.assertIn("define i32 @main()", llvm_ir)
        self.assertIn("%result = call i64 @answer()", llvm_ir)
        self.assertIn("%exit = trunc i64 %result to i32", llvm_ir)

    def test_emits_string_return_with_puts_wrapper(self) -> None:
        module = lower_source_to_ir(
            'def message() -> str:\n    return "ok"\n',
            filename="string.py",
            entry="message",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn('c"ok\\00"', llvm_ir)
        self.assertIn("declare i32 @puts(ptr)", llvm_ir)
        self.assertIn("%printed = call i32 @puts(ptr %result)", llvm_ir)

    def test_emits_record_type_and_method_call(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "    def total(self) -> int64:\n"
            "        return self.left + self.right\n"
            "def entry() -> int64:\n"
            "    pair = Pair(2, 3)\n"
            "    return pair.total()\n"
        )
        llvm_ir = emit_llvm_text(lower_source_to_ir(source, filename="method.py", entry="entry"))
        self.assertIn("%Pair = type { i64, i64 }", llvm_ir)
        self.assertIn("define i64 @Pair.total(ptr %self)", llvm_ir)
        self.assertIn("call i64 @Pair.total(ptr %pair)", llvm_ir)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run LLVM tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_llvm.AotLlvmTextTests -v
```

Expected: import failure for `emit_llvm_text`.

- [ ] **Step 3: Implement textual LLVM emission**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/llvm_text.py` with an
`emit_llvm_text(module: IrModule) -> str` function and a small `_Emitter` class.
The emitter must:

- print target-independent LLVM IR without using `xcc.llvm_api`
- emit record declarations before functions
- map `IrIntType(64, signed=True)` and `IrIntType(64, signed=False)` to `i64`
- map `IrStringType` to `ptr`
- map `IrRecordType` parameters and local variables to stack pointers
- emit integer constants, binary `add/sub/mul`, record constructor stack stores,
  field `getelementptr`/`load`, method calls, returns, and the `main` wrapper
- raise `AotError` with `XCC-AOT-LLVM-0001` for unsupported IR nodes

Use deterministic names:

```python
def _tmp(self, prefix: str) -> str:
    self.index += 1
    return f"%{prefix}{self.index}"
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py` to export
`emit_llvm_text`.

- [ ] **Step 4: Run LLVM text tests**

Run:

```bash
uv run python -m unittest tests.test_aot_llvm -v
```

Expected: all LLVM text tests pass.

- [ ] **Step 5: Commit LLVM text emitter**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/llvm_text.py tests/test_aot_llvm.py
git commit -m "feat: emit LLVM text for AOT smoke IR"
```

## Task 5: Native Oracle Harness

**Files:**
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/native.py`
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot_native.py`

- [ ] **Step 1: Write failing mocked harness tests**

Create `/Users/tcztzy/GitHub/xcc/tests/test_aot_native.py`:

```python
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, NativeSmokeResult, run_native_smoke


class AotNativeHarnessTests(unittest.TestCase):
    def test_native_smoke_writes_llvm_runs_llc_links_and_executes(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(cmd, **kwargs):
            command = tuple(str(part) for part in cmd)
            calls.append(command)
            if command[0] == "/tool/llc":
                Path(command[-1]).write_bytes(b"object")
            if command[0] == "cc":
                Path(command[-1]).write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("xcc.aot.native.subprocess.run", side_effect=fake_run):
            result = run_native_smoke(
                "int64 = int\ndef answer() -> int64:\n    return 42\n",
                entry="answer",
                llc="/tool/llc",
                cc="cc",
            )

        self.assertIsInstance(result, NativeSmokeResult)
        self.assertEqual(result.python_result, 42)
        self.assertEqual(result.native_returncode, 42)
        self.assertTrue(any(command[0] == "/tool/llc" for command in calls))
        self.assertTrue(any(command[0] == "cc" for command in calls))

    def test_native_smoke_reports_tool_failure(self) -> None:
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed")

        with patch("xcc.aot.native.subprocess.run", side_effect=fake_run):
            with self.assertRaises(AotError) as ctx:
                run_native_smoke(
                    "int64 = int\ndef answer() -> int64:\n    return 42\n",
                    entry="answer",
                    llc="/tool/llc",
                    cc="cc",
                )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-NATIVE-0001")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run mocked harness tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_native.AotNativeHarnessTests -v
```

Expected: import failure for `run_native_smoke`.

- [ ] **Step 3: Implement native smoke harness**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/native.py`:

```python
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir


@dataclass(frozen=True)
class NativeSmokeResult:
    python_result: object
    native_returncode: int
    native_stdout: str
    native_stderr: str
    llvm_ir: str


def run_native_smoke(
    source: str,
    *,
    entry: str,
    filename: str = "<smoke>",
    llc: str | None = None,
    cc: str = "cc",
) -> NativeSmokeResult:
    python_result = _run_python_entry(source, entry)
    module = lower_source_to_ir(source, filename=filename, entry=entry)
    llvm_ir = emit_llvm_text(module)
    llc_path = llc or os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ll_path = root / "module.ll"
        obj_path = root / "module.o"
        exe_path = root / "module"
        ll_path.write_text(llvm_ir, encoding="utf-8")
        _run_tool((llc_path, "-filetype=obj", str(ll_path), "-o", str(obj_path)), filename)
        _run_tool((cc, str(obj_path), "-o", str(exe_path)), filename)
        completed = subprocess.run((str(exe_path),), check=False, capture_output=True, text=True)
    return NativeSmokeResult(
        python_result,
        completed.returncode,
        completed.stdout,
        completed.stderr,
        llvm_ir,
    )


def _run_python_entry(source: str, entry: str) -> object:
    namespace: dict[str, object] = {}
    exec(source, namespace)
    function = namespace[entry]
    if not callable(function):
        raise TypeError(f"{entry} is not callable")
    return function()


def _run_tool(command: tuple[str, ...], filename: str) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"command failed: {' '.join(command)}"
        raise AotError((AotDiagnostic("XCC-AOT-NATIVE-0001", message, filename=filename),))
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py` to export
`NativeSmokeResult` and `run_native_smoke`.

- [ ] **Step 4: Run mocked native tests**

Run:

```bash
uv run python -m unittest tests.test_aot_native.AotNativeHarnessTests -v
```

Expected: all mocked harness tests pass.

- [ ] **Step 5: Add optional real native smoke tests**

Append to `/Users/tcztzy/GitHub/xcc/tests/test_aot_native.py`:

```python
import os


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotNativeRealSmokeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_scalar_native_smoke_matches_cpython_exit_code(self) -> None:
        result = run_native_smoke(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            entry="answer",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, 42)
        self.assertEqual(result.native_returncode, 42)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_string_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke('def message() -> str:\n    return "ok"\n', entry="message", llc=_real_llc())
        self.assertEqual(result.python_result, "ok")
        self.assertEqual(result.native_stdout, "ok\n")
        self.assertEqual(result.native_returncode, 0)
```

- [ ] **Step 6: Run native tests**

Run:

```bash
uv run python -m unittest tests.test_aot_native -v
```

Expected: mocked tests pass; real tests pass when `/opt/homebrew/opt/llvm/bin/llc`
or `XCC_LLC` exists, otherwise they skip with the explicit skip reason.

- [ ] **Step 7: Commit native harness**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/native.py tests/test_aot_native.py
git commit -m "feat: add AOT native smoke harness"
```

## Task 6: Milestone 2 Gates and Status

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/CHANGELOG.md`

- [ ] **Step 1: Update changelog**

Add this bullet at the top of `## Current`:

```markdown
- Added Milestone 2 AOT native smoke support: a small AOT IR, AST-to-IR lowering
  for scalar functions, fixed dataclass records, methods, string returns, and
  explicit status-return fixtures, textual LLVM IR emission, and a native oracle
  harness that compiles through `llc` and compares CPython/native behavior.
```

- [ ] **Step 2: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot tests.test_aot_ir tests.test_aot_llvm tests.test_aot_native -v
```

Expected: all focused AOT tests pass; optional real native tests either pass or
skip only because `llc` is unavailable.

- [ ] **Step 3: Run full py311 gate**

Run:

```bash
uv run tox -e py311
```

Expected: full test suite passes with 100.00% coverage.

- [ ] **Step 4: Run handoff gates**

Run:

```bash
uv run tox -e lint
uv run tox -e type
```

Expected: lint and type gates pass.

- [ ] **Step 5: Commit Milestone 2 status**

Run:

```bash
git add CHANGELOG.md
git commit -m "docs: record AOT milestone 2 status"
```

## Final Review Checklist

- [ ] `src/xcc/aot` remains independent from the existing C compiler CLI path.
- [ ] Milestone 2 emits textual LLVM IR and does not use `xcc.llvm_api` or
  libLLVM bindings.
- [ ] Native object generation goes through `llc`, defaulting to
  `/opt/homebrew/opt/llvm/bin/llc` unless `XCC_LLC` is provided.
- [ ] CPython/native oracle tests cover integer return, string stdout, fixed
  dataclass record field reads, method call lowering, and native tool failures.
- [ ] Unsupported lowering and unsupported IR nodes fail with deterministic
  diagnostics.
- [ ] No new Python syntax, decorators, pragmas, or comment directives were
  introduced.
- [ ] No `from __future__ import annotations` was added.
- [ ] Runtime source uses only Python standard library imports.
- [ ] `uv run tox -e py311`, `uv run tox -e lint`, and `uv run tox -e type`
  pass before handoff.
