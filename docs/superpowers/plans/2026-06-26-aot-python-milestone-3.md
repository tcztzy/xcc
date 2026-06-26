# AOT Python Milestone 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile and validate the first real XCC core module slice: `src/xcc/types.py`, `src/xcc/diag.py`, and `src/xcc/options.py`.

**Architecture:** Extend the independent `xcc.aot` pipeline from Milestone 2 smoke snippets to a small module-graph compiler for three real project modules. Native oracle tests must construct supported fixture objects, call lowered symbols from the compiled module graph, and compare observable stdout/status with CPython; generated LLVM must not hard-code expected oracle output as the implementation.

**Tech Stack:** Python 3.11+ standard library, `ast`, frozen dataclasses, textual LLVM IR, `/opt/homebrew/opt/llvm/bin/llc` or `XCC_LLC`, `unittest`, existing `tox` gates.

---

## Scope Check

This plan implements Milestone 3 from `docs/superpowers/specs/2026-06-26-aot-python-design.md`.

In scope:

- `src/xcc/types.py`
- `src/xcc/diag.py`
- `src/xcc/options.py`
- CPython/native oracle tests for:
  - `Type.__str__`
  - `Type.pointer_to`
  - `Type.pointee`
  - `Type.array_of`
  - `Type.element_type`
  - `Type.function_of`
  - `Type.callable_signature`
  - `Type.decay_parameter_type`
  - `Diagnostic.__str__`
  - `FrontendOptions.__post_init__`
  - `normalize_options`

Out of scope:

- `src/xcc/ast.py` and `src/xcc/lexer.py`; these are Milestone 4.
- Parser, sema, and backend modules; these are Milestone 5+.
- General CPython runtime compatibility.
- Arbitrary stdlib or reflection support.

## File Structure

- Create: `src/xcc/aot/slice.py`
  - Collects approved core-slice paths, lowers a multi-module graph, namespaces lowered symbols, and builds native entry wrappers.
- Create: `src/xcc/aot/core_runtime.py`
  - Emits textual LLVM helper declarations/definitions for strings, tuple-like arrays, status returns, and printing.
- Modify: `src/xcc/aot/types.py`
  - Describes composite annotations and aliases used by the core slice.
- Modify: `src/xcc/aot/binder.py`
  - Binds PEP 604 unions, subscript annotations, type aliases, class bases, and dataclass defaults.
- Modify: `src/xcc/aot/ir.py`
  - Adds IR for bool/none/tuple-like values, control flow, print, status raise, string operations, tuple operations, and runtime calls.
- Modify: `src/xcc/aot/lower.py`
  - Lowers the exact core-slice syntax needed by `types.py`, `diag.py`, and `options.py`.
- Modify: `src/xcc/aot/llvm_text.py`
  - Emits the new IR and links `core_runtime.py` helpers.
- Modify: `src/xcc/aot/native.py`
  - Adds `run_native_core_smoke()` for multi-module CPython/native oracle tests.
- Modify: `src/xcc/aot/__init__.py`
  - Exports new public AOT APIs.
- Create: `tests/test_aot_milestone3.py`
  - Focused tests for admission, binding, lowering, LLVM emission, and native core oracle behavior.
- Modify: `CHANGELOG.md`
  - Records Milestone 3 status after implementation and gates.
- Modify: `LESSONS.md`
  - Only if implementation reveals a reusable repository lesson.

## Diagnostic Codes

Use these exact new codes:

- `XCC-AOT-SLICE-0001`: requested module is outside the approved compile set.
- `XCC-AOT-SLICE-0002`: requested entry or fixture cannot be built from lowered symbols.
- `XCC-AOT-TYPE-0004`: unsupported composite annotation.
- `XCC-AOT-TYPE-0005`: unsupported class base or dataclass default.
- `XCC-AOT-LOWER-0004`: unsupported control-flow lowering.
- `XCC-AOT-LOWER-0005`: unsupported runtime operation lowering.
- `XCC-AOT-RUNTIME-0001`: unsupported runtime helper request.

## Task 1: Core Slice Admission and Module Graph

**Files:**

- Create: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/__init__.py`
- Create: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Write failing admission tests**

Create `tests/test_aot_milestone3.py`:

```python
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, collect_slice_inputs


ROOT = Path(__file__).resolve().parents[1]
CORE_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/diag.py",
    ROOT / "src/xcc/options.py",
)


class AotMilestone3SliceTests(unittest.TestCase):
    def test_collects_core_slice_in_deterministic_order(self) -> None:
        modules = collect_slice_inputs(CORE_SLICE)
        self.assertEqual(
            [module.name for module in modules],
            ["xcc.diag", "xcc.options", "xcc.types"],
        )
        self.assertEqual(
            [module.path.name for module in modules],
            ["diag.py", "options.py", "types.py"],
        )

    def test_rejects_module_outside_src_xcc(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_slice_inputs((ROOT / "tests/test_aot.py",))
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SLICE-0001")
```

- [ ] **Step 2: Run admission tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3SliceTests -v
```

Expected: import failure for `collect_slice_inputs`.

- [ ] **Step 3: Implement deterministic slice input collection**

Create `src/xcc/aot/slice.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError


@dataclass(frozen=True)
class AotSliceInput:
    name: str
    path: Path


def collect_slice_inputs(paths: tuple[Path, ...]) -> tuple[AotSliceInput, ...]:
    root = (Path.cwd() / "src" / "xcc").resolve()
    modules: list[AotSliceInput] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is outside src/xcc: {resolved}",
                        filename=str(resolved),
                    ),
                )
            ) from exc
        if relative.suffix != ".py":
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is not Python source: {resolved}",
                        filename=str(resolved),
                    ),
                )
            )
        modules.append(AotSliceInput("xcc." + ".".join(relative.with_suffix("").parts), resolved))
    return tuple(sorted(modules, key=lambda module: module.name))
```

Update `src/xcc/aot/__init__.py`:

```python
from xcc.aot.slice import AotSliceInput, collect_slice_inputs
```

Add `"AotSliceInput"` and `"collect_slice_inputs"` to `__all__`.

- [ ] **Step 4: Run admission tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3SliceTests -v
```

Expected: tests pass.

- [ ] **Step 5: Commit admission foundation**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/slice.py tests/test_aot_milestone3.py
git commit -m "feat: add AOT core slice inputs"
```

## Task 2: Composite Annotation Binding

**Files:**

- Modify: `src/xcc/aot/types.py`
- Modify: `src/xcc/aot/binder.py`
- Modify: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Add failing annotation tests**

Append to `tests/test_aot_milestone3.py`:

```python
from xcc.aot import analyze_path


class AotMilestone3AnnotationTests(unittest.TestCase):
    def test_analyzes_core_slice_annotations(self) -> None:
        for path in CORE_SLICE:
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.summary.functions), 0)

    def test_binds_type_aliases_and_bases(self) -> None:
        analysis = analyze_path(ROOT / "src/xcc/types.py")
        self.assertIn("Type", analysis.types.classes)
        self.assertIn("FunctionParams", analysis.types.aliases)
        self.assertEqual(
            analysis.types.aliases["FunctionParams"].name,
            'tuple[tuple["Type", ...] | None, bool]',
        )
```

- [ ] **Step 2: Run annotation tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3AnnotationTests -v
```

Expected: failures for unsupported subscript/union annotations and missing `aliases`.

- [ ] **Step 3: Extend type metadata**

Modify `src/xcc/aot/types.py`:

```python
@dataclass(frozen=True)
class AotClassInfo:
    name: str
    fields: dict[str, AotType]
    bases: tuple[str, ...] = ()


@dataclass(frozen=True)
class AotTypeAnalysis:
    filename: str
    width_aliases: dict[str, AotType]
    classes: dict[str, AotClassInfo]
    functions: dict[str, AotFunctionInfo]
    aliases: dict[str, AotType]
```

Extend `_BUILTIN_TYPES`:

```python
_BUILTIN_TYPES = {"bool", "int", "None", "object", "str", "ValueError"}
```

Replace `annotation_name()` with:

```python
def annotation_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{annotation_name(node.left)} | {annotation_name(node.right)}"
    if isinstance(node, ast.Subscript):
        return ast.unparse(node)
    if isinstance(node, ast.Tuple):
        return ", ".join(annotation_name(element) for element in node.elts)
    return ast.unparse(node)
```

- [ ] **Step 4: Bind aliases, bases, and composite annotations**

Modify `src/xcc/aot/binder.py`:

```python
self.aliases: dict[str, AotType] = {}
```

Call `_collect_type_aliases()` after `_collect_width_aliases()`.

Add:

```python
def _collect_type_aliases(self) -> None:
    for statement in self.module.tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        name = statement.targets[0].id
        if name in self.width_aliases:
            continue
        if name[:1].isupper() or name.endswith("Params") or name.endswith("Op"):
            self.aliases[name] = AotType(annotation_name(statement.value))
```

Record bases in `_collect_classes()`:

```python
bases = tuple(annotation_name(base) for base in statement.bases)
self.classes[statement.name] = AotClassInfo(statement.name, fields, bases)
```

Return `aliases=dict(self.aliases)` from `AotTypeAnalysis`.

Replace the unsupported annotation branch in `_resolve_annotation()`:

```python
if name in self.aliases:
    return self.aliases[name]
if _is_supported_composite_annotation(name):
    return AotType(name)
self._add_error("XCC-AOT-TYPE-0004", f"Unsupported composite annotation: {name}", owner)
return AotType(name)
```

Add:

```python
def _is_supported_composite_annotation(name: str) -> bool:
    return name.startswith(("tuple[", "Literal[")) or " | " in name
```

- [ ] **Step 5: Run annotation tests**

Run:

```bash
uv run python -m unittest tests.test_aot tests.test_aot_milestone3.AotMilestone3AnnotationTests -v
```

Expected: tests pass.

- [ ] **Step 6: Commit annotation binding**

Run:

```bash
git add src/xcc/aot/types.py src/xcc/aot/binder.py tests/test_aot_milestone3.py
git commit -m "feat: bind AOT core annotations"
```

## Task 3: IR and Runtime Surface for Core Modules

**Files:**

- Modify: `src/xcc/aot/ir.py`
- Modify: `src/xcc/aot/__init__.py`
- Create: `src/xcc/aot/core_runtime.py`
- Modify: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Add failing IR tests**

Append:

```python
from xcc.aot import (
    IrBoolType,
    IrBranch,
    IrConstBool,
    IrConstNone,
    IrForEach,
    IrIf,
    IrNoneType,
    IrPrint,
    IrRaise,
    IrStringConcat,
    IrStringJoin,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
)


class AotMilestone3IrTests(unittest.TestCase):
    def test_models_core_value_types_and_string_operations(self) -> None:
        tuple_type = IrTupleType((IrStringType(), IrBoolType()))
        tuple_expr = IrTuple((IrConstString("x"), IrConstBool(True)), tuple_type)
        self.assertEqual(tuple_expr.type, tuple_type)
        self.assertEqual(IrConstNone().type, IrNoneType())
        self.assertEqual(IrStringConcat((IrConstString("a"), IrConstString("b"))).type, IrStringType())
        self.assertEqual(IrStringJoin(IrConstString(","), IrName("parts", tuple_type)).type, IrStringType())
        self.assertEqual(IrTupleSlice(IrName("parts", tuple_type), 1, None).type, tuple_type)

    def test_models_core_control_flow_and_status(self) -> None:
        int64 = IrIntType(64, signed=True)
        branch = IrBranch((IrReturn(IrConstInt(1, int64)),))
        node = IrIf(IrConstBool(True), branch, IrBranch((IrReturn(IrConstInt(0, int64)),)))
        loop = IrForEach("item", IrName("items", IrTupleType((IrStringType(),))), branch)
        self.assertEqual(node.then_branch.statements[0].value.value, 1)
        self.assertEqual(loop.target, "item")
        self.assertEqual(IrRaise("ValueError", IrConstString("bad")).exception, "ValueError")
        self.assertEqual(IrPrint(IrConstString("ok")).value.value, "ok")
```

- [ ] **Step 2: Run IR tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3IrTests -v
```

Expected: import failures for the new IR names.

- [ ] **Step 3: Add IR dataclasses**

Modify `src/xcc/aot/ir.py` with frozen dataclasses:

```python
@dataclass(frozen=True)
class IrBoolType:
    pass


@dataclass(frozen=True)
class IrNoneType:
    pass


@dataclass(frozen=True)
class IrTupleType:
    elements: tuple[IrType, ...]


@dataclass(frozen=True)
class IrConstBool:
    value: bool

    @property
    def type(self) -> IrBoolType:
        return IrBoolType()


@dataclass(frozen=True)
class IrConstNone:
    @property
    def type(self) -> IrNoneType:
        return IrNoneType()


@dataclass(frozen=True)
class IrTuple:
    elements: tuple["IrExpr", ...]
    type: IrTupleType


@dataclass(frozen=True)
class IrTupleSlice:
    value: "IrExpr"
    start: int | None
    stop: int | None
    type: IrTupleType


@dataclass(frozen=True)
class IrStringConcat:
    parts: tuple["IrExpr", ...]

    @property
    def type(self) -> IrStringType:
        return IrStringType()


@dataclass(frozen=True)
class IrStringJoin:
    separator: "IrExpr"
    values: "IrExpr"

    @property
    def type(self) -> IrStringType:
        return IrStringType()


@dataclass(frozen=True)
class IrBranch:
    statements: tuple["IrStmt", ...]


@dataclass(frozen=True)
class IrIf:
    condition: "IrExpr"
    then_branch: IrBranch
    else_branch: IrBranch | None = None


@dataclass(frozen=True)
class IrForEach:
    target: str
    iterable: "IrExpr"
    body: IrBranch


@dataclass(frozen=True)
class IrPrint:
    value: "IrExpr"


@dataclass(frozen=True)
class IrRaise:
    exception: str
    message: "IrExpr"
```

Extend `IrType`, `IrExpr`, and `IrStmt`, then export all new names from `src/xcc/aot/__init__.py`.

- [ ] **Step 4: Add runtime prelude**

Create `src/xcc/aot/core_runtime.py`:

```python
def runtime_prelude() -> str:
    return "\n".join(
        (
            "declare i32 @puts(ptr)",
            "declare ptr @malloc(i64)",
            "declare i64 @strlen(ptr)",
            "declare ptr @memcpy(ptr, ptr, i64)",
            "declare i32 @strcmp(ptr, ptr)",
            "declare i32 @snprintf(ptr, i64, ptr, ...)",
            "",
            "define ptr @__xcc_aot_string_concat2(ptr %left, ptr %right) {",
            "entry:",
            "  ; Implemented in Task 5 before native core oracle tests run.",
            "  ret ptr %left",
            "}",
        )
    )
```

- [ ] **Step 5: Run IR tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3IrTests tests.test_aot_ir -v
```

Expected: tests pass.

- [ ] **Step 6: Commit IR/runtime surface**

Run:

```bash
git add src/xcc/aot/ir.py src/xcc/aot/__init__.py src/xcc/aot/core_runtime.py tests/test_aot_milestone3.py
git commit -m "feat: extend AOT IR for core modules"
```

## Task 4: Lower Core Module Shapes

**Files:**

- Modify: `src/xcc/aot/lower.py`
- Modify: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Add failing lowering tests**

Append:

```python
from xcc.aot import lower_source_to_ir


class AotMilestone3LoweringTests(unittest.TestCase):
    def test_lowers_diagnostic_options_and_type_methods(self) -> None:
        cases = (
            (ROOT / "src/xcc/diag.py", "Diagnostic.__str__"),
            (ROOT / "src/xcc/options.py", "FrontendOptions.__post_init__"),
            (ROOT / "src/xcc/types.py", "Type.__str__"),
        )
        for path, entry in cases:
            with self.subTest(path=path.name, entry=entry):
                module = lower_source_to_ir(path.read_text(encoding="utf-8"), filename=str(path), entry=entry)
                self.assertIn(entry, {function.name for function in module.functions})

    def test_lowers_type_transformation_methods(self) -> None:
        source = (ROOT / "src/xcc/types.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(source, filename="src/xcc/types.py", entry="Type.pointer_to")
        names = {function.name for function in module.functions}
        self.assertIn("Type.pointer_to", names)
        self.assertIn("Type.array_of", names)
        self.assertIn("Type.callable_signature", names)
```

- [ ] **Step 2: Run lowering tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3LoweringTests -v
```

Expected: failures for unsupported annotations, `if`, `for`, `raise`, tuple operations, f-strings, `object.__setattr__`, and list/string operations.

- [ ] **Step 3: Lower control flow and status**

Modify `src/xcc/aot/lower.py`:

- `ast.If` lowers to `IrIf`.
- `ast.For` over accepted tuple/list values lowers to `IrForEach`.
- `ast.Raise(ValueError(message))` lowers to `IrRaise("ValueError", message)`.
- `return None` lowers to `IrReturn(IrConstNone())`.
- `bool`, `None`, `tuple[...]`, `Literal[...]`, and `T | None` annotations lower to the new IR types.

Use these exact diagnostics:

```python
self._error("XCC-AOT-LOWER-0004", "Unsupported control-flow lowering: <shape>", node)
self._error("XCC-AOT-LOWER-0005", "Unsupported runtime operation lowering: <shape>", node)
```

- [ ] **Step 4: Lower strings, tuples, and frozen dataclass initialization**

Modify `src/xcc/aot/lower.py`:

- f-strings lower to `IrStringConcat`.
- `"".join(parts)` lowers to `IrStringJoin`.
- tuple literals lower to `IrTuple`.
- tuple concatenation lowers to `IrCall("__tuple_concat", ...)`.
- tuple slicing lowers to `IrTupleSlice`.
- `object.__setattr__(self, "field", value)` inside `__post_init__` lowers to an assignment to the existing record field.
- `suffix.append(value)` lowers to `IrCall("__tuple_append", ...)` for the Milestone 3 tuple-like builder.

- [ ] **Step 5: Run lowering tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3LoweringTests tests.test_aot_ir -v
```

Expected: lowering tests pass.

- [ ] **Step 6: Commit core lowering**

Run:

```bash
git add src/xcc/aot/lower.py tests/test_aot_milestone3.py
git commit -m "feat: lower AOT core module shapes"
```

## Task 5: LLVM Emission for Core IR

**Files:**

- Modify: `src/xcc/aot/core_runtime.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Add failing LLVM tests**

Append:

```python
from xcc.aot import emit_llvm_text


class AotMilestone3LlvmTests(unittest.TestCase):
    def test_emits_if_print_raise_and_runtime_string_calls(self) -> None:
        int32 = IrIntType(32, signed=True)
        module = IrModule(
            "core_ir.py",
            (),
            (
                IrFunction(
                    "entry",
                    (),
                    int32,
                    (
                        IrIf(
                            IrConstBool(True),
                            IrBranch((IrPrint(IrConstString("ok")),)),
                            IrBranch((IrRaise("ValueError", IrConstString("bad")),)),
                        ),
                        IrReturn(IrConstInt(0, int32)),
                    ),
                ),
            ),
            entry="entry",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("br i1 true", llvm_ir)
        self.assertIn("call i32 @puts", llvm_ir)
        self.assertIn("ret i32 2", llvm_ir)

    def test_emits_string_concat_runtime_call(self) -> None:
        module = IrModule(
            "concat.py",
            (),
            (
                IrFunction(
                    "entry",
                    (),
                    IrStringType(),
                    (IrReturn(IrStringConcat((IrConstString("a"), IrConstString("b")))),),
                ),
            ),
            entry="entry",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("@__xcc_aot_string_concat2", llvm_ir)
```

- [ ] **Step 2: Run LLVM tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3LlvmTests -v
```

Expected: `XCC-AOT-LLVM-0001` failures for the new IR nodes.

- [ ] **Step 3: Emit control flow, print, raise, and core runtime calls**

Modify `src/xcc/aot/llvm_text.py`:

- `IrIf` emits labels and conditional branches.
- `IrForEach` emits a counted loop over tuple-like runtime arrays.
- `IrPrint` emits `puts`.
- `IrRaise` emits `puts` for the error message and `ret i32 2`.
- `IrConstBool` emits `true`/`false`.
- `IrConstNone` emits zero/null according to context.
- `IrStringConcat` emits `@__xcc_aot_string_concat2`.
- `IrStringJoin`, `IrTuple`, `IrTupleSlice`, and tuple helper calls emit runtime helper calls.

Prepend `runtime_prelude()` only when at least one runtime helper is referenced.

- [ ] **Step 4: Complete string concat runtime helper**

Replace the stub in `src/xcc/aot/core_runtime.py` with LLVM that:

- reads left/right byte lengths with `strlen`
- allocates `left_len + right_len + 1` bytes with `malloc`
- copies left bytes and right bytes with `memcpy`
- writes a trailing zero byte
- returns the allocated pointer

- [ ] **Step 5: Run LLVM tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3LlvmTests tests.test_aot_llvm -v
```

Expected: tests pass.

- [ ] **Step 6: Commit LLVM core emission**

Run:

```bash
git add src/xcc/aot/core_runtime.py src/xcc/aot/llvm_text.py tests/test_aot_milestone3.py
git commit -m "feat: emit LLVM for AOT core IR"
```

## Task 6: Native Core Oracle Harness

**Files:**

- Modify: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/native.py`
- Modify: `src/xcc/aot/__init__.py`
- Modify: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Add failing mocked harness test**

Append:

```python
from xcc.aot import run_native_core_smoke


class AotMilestone3CoreHarnessTests(unittest.TestCase):
    def test_core_smoke_calls_lowered_entry_symbol(self) -> None:
        def fake_run(cmd, **kwargs):
            command = tuple(str(part) for part in cmd)
            if command[0] == "/tool/llc":
                llvm_ir = Path(command[2]).read_text(encoding="utf-8")
                self.assertIn("@xcc.diag.Diagnostic.__str__", llvm_ir)
                self.assertNotIn("input.c:7:3: parse: expected", llvm_ir)
                Path(command[-1]).write_bytes(b"object")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if command[0] == "cc":
                Path(command[-1]).write_text("#!/bin/sh\nprintf 'ok\\n'\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

        with patch("xcc.aot.native.subprocess.run", side_effect=fake_run):
            result = run_native_core_smoke(
                CORE_SLICE,
                entry="xcc.diag:Diagnostic.__str__",
                fixture="diag_with_location",
                llc="/tool/llc",
                cc="cc",
            )
        self.assertEqual(result.native_stdout, "ok\n")
```

- [ ] **Step 2: Run mocked harness test and verify it fails**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3CoreHarnessTests -v
```

Expected: import failure for `run_native_core_smoke`.

- [ ] **Step 3: Implement multi-module lowering and namespacing**

Add to `src/xcc/aot/slice.py`:

```python
from xcc.aot.ir import IrFunction, IrModule
from xcc.aot.lower import lower_source_to_ir


def lower_core_slice(paths: tuple[Path, ...]) -> IrModule:
    records = []
    functions: list[IrFunction] = []
    for module_input in collect_slice_inputs(paths):
        source = module_input.path.read_text(encoding="utf-8")
        module = lower_source_to_ir(source, filename=str(module_input.path))
        records.extend(module.records)
        prefix = module_input.name
        for function in module.functions:
            functions.append(
                IrFunction(
                    f"{prefix}.{function.name}",
                    function.params,
                    function.return_type,
                    function.body,
                )
            )
    return IrModule("<core-slice>", tuple(records), tuple(functions))
```

- [ ] **Step 4: Implement entry wrappers that call lowered symbols**

Add `core_entry_wrapper(entry: str, fixture: str) -> IrFunction` to `src/xcc/aot/slice.py`.

Required wrappers:

- `xcc.diag:Diagnostic.__str__` / `diag_with_location`
  - constructs a `Diagnostic` record with stage `parse`, filename `input.c`, message `expected ';'`, line `7`, column `3`, and code `None`
  - calls `xcc.diag.Diagnostic.__str__`
  - prints the returned string
  - returns `0`
- `xcc.options:FrontendOptions.__post_init__` / `bad_std`
  - constructs `FrontendOptions(std="c99")`
  - calls `xcc.options.FrontendOptions.__post_init__`
  - if the lowered function raises, prints the message and returns `2`
- `xcc.types:Type.pointer_array_str` / `int_pointer_array`
  - constructs `Type("int")`
  - calls `Type.pointer_to`
  - calls `Type.array_of(4)`
  - calls `Type.__str__`
  - prints the returned string

Unknown entry/fixture pairs raise `XCC-AOT-SLICE-0002`.

- [ ] **Step 5: Implement `run_native_core_smoke`**

Modify `src/xcc/aot/native.py`:

```python
def run_native_core_smoke(
    paths: tuple[Path, ...],
    *,
    entry: str,
    fixture: str,
    llc: str | None = None,
    cc: str = "cc",
) -> NativeSmokeResult:
    module = lower_core_slice(paths)
    wrapper = core_entry_wrapper(entry, fixture)
    module = IrModule(module.filename, module.records, module.functions + (wrapper,), entry=wrapper.name)
    llvm_ir = emit_llvm_text(module)
    llc_path = llc or os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ll_path = root / "core.ll"
        obj_path = root / "core.o"
        exe_path = root / "core"
        ll_path.write_text(llvm_ir, encoding="utf-8")
        _run_tool((llc_path, "-filetype=obj", str(ll_path), "-o", str(obj_path)), "<core>")
        _run_tool((cc, str(obj_path), "-o", str(exe_path)), "<core>")
        completed = subprocess.run((str(exe_path),), check=False, capture_output=True, text=True)
    return NativeSmokeResult(None, completed.returncode, completed.stdout, completed.stderr, llvm_ir)
```

Export `lower_core_slice`, `core_entry_wrapper`, and `run_native_core_smoke`.

- [ ] **Step 6: Run mocked harness test**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3CoreHarnessTests -v
```

Expected: mocked harness test passes and verifies the generated LLVM calls a lowered symbol rather than embedding expected output.

- [ ] **Step 7: Commit core harness**

Run:

```bash
git add src/xcc/aot/slice.py src/xcc/aot/native.py src/xcc/aot/__init__.py tests/test_aot_milestone3.py
git commit -m "feat: add lowered AOT core native harness"
```

## Task 7: Native Oracle for Core Behaviors

**Files:**

- Modify: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/lower.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `src/xcc/aot/core_runtime.py`
- Modify: `tests/test_aot_milestone3.py`

- [ ] **Step 1: Add real native oracle tests**

Append:

```python
import os


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotMilestone3CoreNativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_diagnostic_str_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            CORE_SLICE,
            entry="xcc.diag:Diagnostic.__str__",
            fixture="diag_with_location",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "input.c:7:3: parse: expected ';'\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_frontend_options_validation_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            CORE_SLICE,
            entry="xcc.options:FrontendOptions.__post_init__",
            fixture="bad_std",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_returncode, 2)
        self.assertIn("Unsupported language standard: c99", result.native_stdout)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_type_pointer_array_str_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            CORE_SLICE,
            entry="xcc.types:Type.pointer_array_str",
            fixture="int_pointer_array",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "int*[4]\n")
        self.assertEqual(result.native_returncode, 0)
```

- [ ] **Step 2: Run real native tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3CoreNativeTests -v
```

Expected: failures until lowering, runtime helpers, and entry wrappers execute real lowered behavior.

- [ ] **Step 3: Complete the missing lowering forms**

Finish the concrete constructs from the three target modules:

- `if`/`else`
- `for kind, value in reversed(self.declarator_ops)`
- generator/list comprehensions used by `_ops_from_legacy` and `__post_init__`
- tuple concatenation, tuple slicing, fixed tuple indexing, and tuple truthiness
- `suffix.append(...)`
- `"".join(...)`
- f-strings with string and integer parts
- `object.__setattr__`
- `is`, `is not`, `in`, `not in`, `==`, `!=`
- `isinstance(value, int)` and `isinstance(value, tuple)`
- `raise ValueError(...)`

Every unsupported shape must use one of the Milestone 3 diagnostics instead of falling through to a Python exception.

- [ ] **Step 4: Complete runtime helpers**

Finish LLVM runtime support for:

- string concat
- string join
- integer-to-string formatting through `snprintf`
- tuple-like fixed arrays for the `Type.declarator_ops` fixtures
- string equality and membership checks needed by `FrontendOptions.__post_init__`

- [ ] **Step 5: Run native oracle tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone3.AotMilestone3CoreNativeTests tests.test_aot_milestone3.AotMilestone3LoweringTests -v
```

Expected: tests pass when `llc` is present; native tests skip only if `llc` is unavailable.

- [ ] **Step 6: Commit native core behavior**

Run:

```bash
git add src/xcc/aot/slice.py src/xcc/aot/core_runtime.py src/xcc/aot/lower.py src/xcc/aot/llvm_text.py tests/test_aot_milestone3.py
git commit -m "feat: validate lowered AOT core behavior natively"
```

## Task 8: Milestone 3 Gates and Status

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `LESSONS.md` only if a new reusable lesson was discovered while implementing.

- [ ] **Step 1: Update changelog**

Add this bullet at the top of `## Current` in `CHANGELOG.md`:

```markdown
- Added Milestone 3 AOT core module support for `types.py`, `diag.py`, and
  `options.py`, including composite annotation binding, core IR/runtime
  operations, lowered multi-module entry wrappers, and CPython/native oracle
  tests that call lowered symbols.
```

- [ ] **Step 2: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot tests.test_aot_ir tests.test_aot_llvm tests.test_aot_native tests.test_aot_milestone3 -v
```

Expected: all focused AOT tests pass; optional real native tests skip only if `llc` is unavailable.

- [ ] **Step 3: Run relevant existing module tests**

Run:

```bash
uv run python -m unittest tests.test_options tests.test_lexer tests.test_frontend -v
```

Expected: existing CPython behavior still passes.

- [ ] **Step 4: Run full py311 gate**

Run:

```bash
uv run tox -e py311
```

Expected: full test suite passes with 100.00% coverage.

- [ ] **Step 5: Run handoff gates**

Run:

```bash
uv run tox -e lint
uv run tox -e type
```

Expected: lint and type gates pass.

- [ ] **Step 6: Commit Milestone 3 status**

Run:

```bash
git add CHANGELOG.md
git commit -m "docs: record AOT milestone 3 status"
```

If `LESSONS.md` changed, include it in the same commit.

## Final Review Checklist

- [ ] `src/xcc/types.py`, `src/xcc/diag.py`, and `src/xcc/options.py` still run under CPython 3.11+.
- [ ] No new Python syntax, Cython-style decorators, pragmas, or comment directives were added.
- [ ] No `from __future__ import annotations` was added.
- [ ] Runtime source uses only Python standard library imports.
- [ ] Width aliases remain ordinary Python-visible aliases.
- [ ] Native core oracle LLVM calls lowered module symbols and does not embed expected output strings as the implementation.
- [ ] Unsupported composite annotations and runtime operations fail with deterministic diagnostics.
- [ ] Native object generation goes through `/opt/homebrew/opt/llvm/bin/llc` unless `XCC_LLC` is set.
- [ ] `uv run tox -e py311`, `uv run tox -e lint`, and `uv run tox -e type` pass before handoff.

## Self-Review

- Spec coverage: this plan covers Milestone 3 only. Milestone 4 lexer/AST work remains out of scope and should get its own plan after Milestone 3 lands.
- Red-flag scan: the plan rejects generated native outputs that bypass lowered symbols. Every implementation task has an explicit test command before its commit step.
- Type consistency: public names introduced here are `AotSliceInput`, `collect_slice_inputs`, `lower_core_slice`, `core_entry_wrapper`, `run_native_core_smoke`, `IrBoolType`, `IrNoneType`, `IrTupleType`, `IrConstBool`, `IrConstNone`, `IrTuple`, `IrTupleSlice`, `IrStringConcat`, `IrStringJoin`, `IrBranch`, `IrIf`, `IrForEach`, `IrPrint`, and `IrRaise`.
