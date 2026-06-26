# AOT Python Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Milestone 1 AOT Python front-end skeleton: parse Python modules, check the approved XCC-Python subset, bind basic annotations and width aliases, and report deterministic diagnostics without emitting LLVM IR.

**Architecture:** Add a small `xcc.aot` package beside the existing compiler code. The first slice uses CPython `ast.parse` as the parser, then runs a subset checker and type binder over a module graph summary; it returns structured analysis objects and diagnostics. No existing `xcc` runtime path changes, and no LLVM/native output is introduced in this milestone.

**Tech Stack:** Python 3.11+ standard library, `ast`, `dataclasses`, `pathlib`, `unittest`, existing `tox` lint/type gates.

---

## Scope Check

The approved design spec covers six milestones and several independent
subsystems: subset checking, type binding, AOT IR, LLVM emission, runtime
objects, native oracle tests, and full bootstrap. This implementation plan
covers only Milestone 1 from
`/Users/tcztzy/GitHub/xcc/docs/superpowers/specs/2026-06-26-aot-python-design.md`:

- create `xcc.aot` modules for parsing, subset checking, diagnostics, and type
  binding
- validate accepted and rejected snippets
- do not emit native code
- do not add width aliases to production XCC modules yet
- do not modify the existing `xcc` CLI

Milestone 2 needs a separate plan after Milestone 1 is implemented and reviewed.

## File Structure

- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`  
  Public AOT analysis API exports.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/diag.py`  
  AOT diagnostic and exception types.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/module.py`  
  Python source parsing and module wrapper.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/subset.py`  
  XCC-Python subset checker and module summary.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/types.py`  
  AOT type representation and annotation parsing helpers.
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/binder.py`  
  Type binder for width aliases, dataclass fields, and function signatures.
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot.py`  
  Focused unit tests for Milestone 1 behavior.
- Modify: `/Users/tcztzy/GitHub/xcc/CHANGELOG.md`  
  Record Milestone 1 capability after implementation passes.

## Diagnostic Codes

Use these exact codes in Milestone 1:

- `XCC-AOT-PARSE-0001`: Python syntax parse failure.
- `XCC-AOT-SUBSET-0001`: unsupported Python syntax node.
- `XCC-AOT-SUBSET-0002`: unsupported decorator.
- `XCC-AOT-SUBSET-0003`: unsupported dynamic call.
- `XCC-AOT-TYPE-0001`: missing function annotation.
- `XCC-AOT-TYPE-0002`: unsupported annotation.
- `XCC-AOT-TYPE-0003`: conflicting width alias.

## Task 1: Diagnostics Package

**Files:**
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/diag.py`
- Create: `/Users/tcztzy/GitHub/xcc/tests/test_aot.py`

- [ ] **Step 1: Write failing diagnostic tests**

Add this initial test file:

```python
import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotDiagnostic, AotError


class AotDiagnosticTests(unittest.TestCase):
    def test_diagnostic_with_location(self) -> None:
        diagnostic = AotDiagnostic(
            "XCC-AOT-SUBSET-0001",
            "Unsupported Python syntax: Lambda",
            filename="sample.py",
            line=3,
            column=5,
        )
        self.assertEqual(
            str(diagnostic),
            "sample.py:3:5: aot: XCC-AOT-SUBSET-0001: Unsupported Python syntax: Lambda",
        )

    def test_diagnostic_without_location(self) -> None:
        diagnostic = AotDiagnostic(
            "XCC-AOT-TYPE-0002",
            "Unsupported annotation: object",
            filename="sample.py",
        )
        self.assertEqual(
            str(diagnostic),
            "sample.py: aot: XCC-AOT-TYPE-0002: Unsupported annotation: object",
        )

    def test_error_wraps_diagnostics(self) -> None:
        first = AotDiagnostic("XCC-AOT-PARSE-0001", "invalid syntax", filename="bad.py")
        second = AotDiagnostic("XCC-AOT-TYPE-0001", "Missing return annotation", filename="bad.py")
        error = AotError((first, second))
        self.assertEqual(error.diagnostics, (first, second))
        self.assertEqual(str(error), "bad.py: aot: XCC-AOT-PARSE-0001: invalid syntax")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
uv run python -m unittest tests.test_aot.AotDiagnosticTests -v
```

Expected: import failure for `xcc.aot`.

- [ ] **Step 3: Implement AOT diagnostic types**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/diag.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class AotDiagnostic:
    code: str
    message: str
    filename: str
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        if self.line is None or self.column is None:
            return f"{self.filename}: aot: {self.code}: {self.message}"
        return f"{self.filename}:{self.line}:{self.column}: aot: {self.code}: {self.message}"


class AotError(ValueError):
    def __init__(self, diagnostics: tuple[AotDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("AotError requires at least one diagnostic")
        super().__init__(str(diagnostics[0]))
        self.diagnostics = diagnostics
```

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`:

```python
from xcc.aot.diag import AotDiagnostic, AotError

__all__ = (
    "AotDiagnostic",
    "AotError",
)
```

- [ ] **Step 4: Run the diagnostic tests and verify they pass**

Run:

```bash
uv run python -m unittest tests.test_aot.AotDiagnosticTests -v
```

Expected: all `AotDiagnosticTests` tests pass.

- [ ] **Step 5: Commit diagnostics package**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/diag.py tests/test_aot.py
git commit -m "feat: add AOT diagnostics"
```

## Task 2: Python Module Parsing

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/module.py`
- Modify: `/Users/tcztzy/GitHub/xcc/tests/test_aot.py`

- [ ] **Step 1: Add failing module parser tests**

Append this class to `/Users/tcztzy/GitHub/xcc/tests/test_aot.py` before the
`if __name__ == "__main__"` block:

```python
from xcc.aot import parse_source


class AotModuleParseTests(unittest.TestCase):
    def test_parse_source_records_filename_and_tree(self) -> None:
        module = parse_source("def f() -> int:\n    return 1\n", filename="sample.py")
        self.assertEqual(module.filename, "sample.py")
        self.assertEqual(module.source, "def f() -> int:\n    return 1\n")
        self.assertEqual(len(module.tree.body), 1)

    def test_parse_source_reports_syntax_error(self) -> None:
        with self.assertRaises(AotError) as ctx:
            parse_source("def bad(:\n    return 1\n", filename="bad.py")
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-PARSE-0001")
        self.assertEqual(diagnostic.filename, "bad.py")
        self.assertEqual(diagnostic.line, 1)
        self.assertIsNotNone(diagnostic.column)
        self.assertIn("invalid syntax", diagnostic.message)
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot.AotModuleParseTests -v
```

Expected: import failure for `parse_source`.

- [ ] **Step 3: Implement module parser**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/module.py`:

```python
import ast
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError


@dataclass(frozen=True)
class AotModule:
    filename: str
    source: str
    tree: ast.Module


def parse_source(source: str, *, filename: str = "<input>") -> AotModule:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as error:
        message = error.msg or "invalid syntax"
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-PARSE-0001",
                    message,
                    filename=filename,
                    line=error.lineno,
                    column=error.offset,
                ),
            )
        ) from error
    return AotModule(filename, source, tree)


def parse_path(path: str | Path) -> AotModule:
    resolved = Path(path)
    source = resolved.read_text(encoding="utf-8", errors="surrogateescape")
    return parse_source(source, filename=str(resolved))
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`:

```python
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule, parse_path, parse_source

__all__ = (
    "AotDiagnostic",
    "AotError",
    "AotModule",
    "parse_path",
    "parse_source",
)
```

- [ ] **Step 4: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot -v
```

Expected: all current AOT diagnostic and module parser tests pass.

- [ ] **Step 5: Commit module parser**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/module.py tests/test_aot.py
git commit -m "feat: parse AOT Python modules"
```

## Task 3: Subset Checker Skeleton

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/subset.py`
- Modify: `/Users/tcztzy/GitHub/xcc/tests/test_aot.py`

- [ ] **Step 1: Add failing subset checker tests**

Append this class to `/Users/tcztzy/GitHub/xcc/tests/test_aot.py` before the
`if __name__ == "__main__"` block:

```python
from xcc.aot import check_subset


class AotSubsetCheckerTests(unittest.TestCase):
    def test_accepts_dataclass_and_typed_function(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Point:\n"
            "    x: int\n"
            "    y: int\n"
            "def add(point: Point) -> int:\n"
            "    return point.x + point.y\n"
        )
        summary = check_subset(parse_source(source, filename="point.py"))
        self.assertEqual(summary.filename, "point.py")
        self.assertEqual(summary.imports, ("dataclasses",))
        self.assertEqual(summary.classes, ("Point",))
        self.assertEqual(summary.functions, ("add",))

    def test_rejects_lambda_expression(self) -> None:
        module = parse_source("value = lambda x: x\n", filename="bad.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0001")
        self.assertEqual(diagnostic.message, "Unsupported Python syntax: Lambda")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 8))

    def test_rejects_custom_decorator(self) -> None:
        source = "def marker(fn):\n    return fn\n@marker\ndef f() -> int:\n    return 1\n"
        module = parse_source(source, filename="decorator.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0002")
        self.assertEqual(diagnostic.message, "Unsupported decorator: marker")

    def test_rejects_dynamic_reflection_call(self) -> None:
        module = parse_source("def f(value: object) -> object:\n    return getattr(value, 'x')\n", filename="bad.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0003")
        self.assertEqual(diagnostic.message, "Unsupported dynamic call: getattr")
```

- [ ] **Step 2: Run subset tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot.AotSubsetCheckerTests -v
```

Expected: import failure for `check_subset`.

- [ ] **Step 3: Implement subset checker**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/subset.py`:

```python
import ast
from dataclasses import dataclass

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule

_DYNAMIC_CALLS = {
    "__import__",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "hasattr",
    "locals",
    "setattr",
}

_UNSUPPORTED_NODES = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.AsyncWith,
    ast.Await,
    ast.Delete,
    ast.Global,
    ast.Lambda,
    ast.Match,
    ast.Nonlocal,
    ast.Yield,
    ast.YieldFrom,
)


@dataclass(frozen=True)
class AotModuleSummary:
    filename: str
    imports: tuple[str, ...]
    classes: tuple[str, ...]
    functions: tuple[str, ...]


def check_subset(module: AotModule) -> AotModuleSummary:
    checker = _SubsetChecker(module.filename)
    checker.visit(module.tree)
    checker.raise_if_errors()
    return AotModuleSummary(
        module.filename,
        tuple(checker.imports),
        tuple(checker.classes),
        tuple(checker.functions),
    )


class _SubsetChecker(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.imports: list[str] = []
        self.classes: list[str] = []
        self.functions: list[str] = []
        self._diagnostics: list[AotDiagnostic] = []

    def raise_if_errors(self) -> None:
        if self._diagnostics:
            raise AotError(tuple(self._diagnostics))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record_import(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is not None:
            self._record_import(node.module)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_decorators(node.decorator_list)
        self.classes.append(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_decorators(node.decorator_list)
        self.functions.append(node.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in _DYNAMIC_CALLS:
            self._add_error(
                "XCC-AOT-SUBSET-0003",
                f"Unsupported dynamic call: {name}",
                node,
            )
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, _UNSUPPORTED_NODES):
            self._add_error(
                "XCC-AOT-SUBSET-0001",
                f"Unsupported Python syntax: {type(node).__name__}",
                node,
            )
            return
        super().generic_visit(node)

    def _record_import(self, module: str) -> None:
        root = module.split(".", 1)[0]
        if root not in self.imports:
            self.imports.append(root)

    def _check_decorators(self, decorators: list[ast.expr]) -> None:
        for decorator in decorators:
            if _is_allowed_decorator(decorator):
                continue
            self._add_error(
                "XCC-AOT-SUBSET-0002",
                f"Unsupported decorator: {ast.unparse(decorator)}",
                decorator,
            )

    def _add_error(self, code: str, message: str, node: ast.AST) -> None:
        self._diagnostics.append(
            AotDiagnostic(
                code,
                message,
                filename=self.filename,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
            )
        )


def _is_allowed_decorator(decorator: ast.expr) -> bool:
    if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
        return True
    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
        if decorator.func.id != "dataclass":
            return False
        for keyword in decorator.keywords:
            if keyword.arg != "frozen":
                return False
            if not isinstance(keyword.value, ast.Constant) or keyword.value.value is not True:
                return False
        return True
    return False


def _call_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    return None
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`:

```python
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset

__all__ = (
    "AotDiagnostic",
    "AotError",
    "AotModule",
    "AotModuleSummary",
    "check_subset",
    "parse_path",
    "parse_source",
)
```

- [ ] **Step 4: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot -v
```

Expected: all current AOT tests pass.

- [ ] **Step 5: Commit subset checker**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/subset.py tests/test_aot.py
git commit -m "feat: add AOT subset checker"
```

## Task 4: Type Model and Binder Skeleton

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/types.py`
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/binder.py`
- Modify: `/Users/tcztzy/GitHub/xcc/tests/test_aot.py`

- [ ] **Step 1: Add failing type binder tests**

Append this class to `/Users/tcztzy/GitHub/xcc/tests/test_aot.py` before the
`if __name__ == "__main__"` block:

```python
from xcc.aot import bind_types


class AotTypeBinderTests(unittest.TestCase):
    def test_binds_width_alias_dataclass_and_function(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    value: int64\n"
            "def unwrap(box: Box) -> int64:\n"
            "    return box.value\n"
        )
        analysis = bind_types(check_subset(parse_source(source, filename="box.py")), parse_source(source, filename="box.py"))
        self.assertEqual(analysis.width_aliases["int64"].bits, 64)
        self.assertTrue(analysis.width_aliases["int64"].signed)
        self.assertEqual(analysis.classes["Box"].fields["value"].name, "int64")
        self.assertEqual(analysis.functions["unwrap"].return_type.name, "int64")
        self.assertEqual(analysis.functions["unwrap"].parameters, (("box", "Box"),))

    def test_binds_unsigned_width_alias(self) -> None:
        source = "uint32 = int\ndef f(value: uint32) -> uint32:\n    return value\n"
        module = parse_source(source, filename="u.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.width_aliases["uint32"].bits, 32)
        self.assertFalse(analysis.width_aliases["uint32"].signed)

    def test_rejects_missing_parameter_annotation(self) -> None:
        source = "def f(value) -> int:\n    return value\n"
        module = parse_source(source, filename="missing.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0001")
        self.assertEqual(diagnostic.message, "Missing annotation for parameter: f.value")

    def test_rejects_unsupported_annotation(self) -> None:
        source = "def f(value: complex) -> complex:\n    return value\n"
        module = parse_source(source, filename="badtype.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0002")
        self.assertEqual(diagnostic.message, "Unsupported annotation: complex")

    def test_rejects_conflicting_width_alias(self) -> None:
        source = "int64 = str\ndef f(value: int64) -> int64:\n    return value\n"
        module = parse_source(source, filename="alias.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0003")
        self.assertEqual(diagnostic.message, "Width alias must target int: int64")
```

- [ ] **Step 2: Run binder tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot.AotTypeBinderTests -v
```

Expected: import failure for `bind_types`.

- [ ] **Step 3: Implement AOT type representation**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/types.py`:

```python
import ast
from dataclasses import dataclass

_BUILTIN_TYPES = {"bool", "int", "None", "str"}
_WIDTH_ALIASES = {
    "int8": (8, True),
    "int16": (16, True),
    "int32": (32, True),
    "int64": (64, True),
    "uint8": (8, False),
    "uint16": (16, False),
    "uint32": (32, False),
    "uint64": (64, False),
    "usize": (64, False),
}


@dataclass(frozen=True)
class AotType:
    name: str
    bits: int | None = None
    signed: bool | None = None


@dataclass(frozen=True)
class AotClassInfo:
    name: str
    fields: dict[str, AotType]


@dataclass(frozen=True)
class AotFunctionInfo:
    name: str
    parameters: tuple[tuple[str, str], ...]
    return_type: AotType


@dataclass(frozen=True)
class AotTypeAnalysis:
    filename: str
    width_aliases: dict[str, AotType]
    classes: dict[str, AotClassInfo]
    functions: dict[str, AotFunctionInfo]


def width_alias_type(name: str) -> AotType | None:
    entry = _WIDTH_ALIASES.get(name)
    if entry is None:
        return None
    bits, signed = entry
    return AotType(name, bits=bits, signed=signed)


def annotation_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return ast.unparse(node)


def is_builtin_type_name(name: str) -> bool:
    return name in _BUILTIN_TYPES
```

- [ ] **Step 4: Implement type binder**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/binder.py`:

```python
import ast

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule
from xcc.aot.subset import AotModuleSummary
from xcc.aot.types import (
    AotClassInfo,
    AotFunctionInfo,
    AotType,
    AotTypeAnalysis,
    annotation_name,
    is_builtin_type_name,
    width_alias_type,
)


def bind_types(summary: AotModuleSummary, module: AotModule) -> AotTypeAnalysis:
    binder = _TypeBinder(summary, module)
    return binder.bind()


class _TypeBinder:
    def __init__(self, summary: AotModuleSummary, module: AotModule) -> None:
        self.summary = summary
        self.module = module
        self.width_aliases: dict[str, AotType] = {}
        self.classes: dict[str, AotClassInfo] = {}
        self.functions: dict[str, AotFunctionInfo] = {}
        self._diagnostics: list[AotDiagnostic] = []

    def bind(self) -> AotTypeAnalysis:
        self._collect_width_aliases()
        self._collect_classes()
        self._collect_functions()
        if self._diagnostics:
            raise AotError(tuple(self._diagnostics))
        return AotTypeAnalysis(
            self.summary.filename,
            dict(self.width_aliases),
            dict(self.classes),
            dict(self.functions),
        )

    def _collect_width_aliases(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                continue
            name = statement.targets[0].id
            alias = width_alias_type(name)
            if alias is None:
                continue
            if not isinstance(statement.value, ast.Name) or statement.value.id != "int":
                self._add_error(
                    "XCC-AOT-TYPE-0003",
                    f"Width alias must target int: {name}",
                    statement,
                )
                continue
            self.width_aliases[name] = alias

    def _collect_classes(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            fields: dict[str, AotType] = {}
            for child in statement.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields[child.target.id] = self._resolve_annotation(child.annotation, child)
            self.classes[statement.name] = AotClassInfo(statement.name, fields)

    def _collect_functions(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.FunctionDef):
                continue
            parameters: list[tuple[str, str]] = []
            for arg in statement.args.posonlyargs + statement.args.args:
                if arg.annotation is None:
                    self._add_error(
                        "XCC-AOT-TYPE-0001",
                        f"Missing annotation for parameter: {statement.name}.{arg.arg}",
                        statement,
                    )
                    continue
                parameters.append((arg.arg, annotation_name(arg.annotation)))
                self._resolve_annotation(arg.annotation, arg)
            if statement.returns is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    f"Missing return annotation for function: {statement.name}",
                    statement,
                )
                return_type = AotType("None")
            else:
                return_type = self._resolve_annotation(statement.returns, statement)
            self.functions[statement.name] = AotFunctionInfo(
                statement.name,
                tuple(parameters),
                return_type,
            )

    def _resolve_annotation(self, node: ast.expr, owner: ast.AST) -> AotType:
        name = annotation_name(node)
        alias = self.width_aliases.get(name)
        if alias is not None:
            return alias
        if name in self.classes or is_builtin_type_name(name):
            return AotType(name)
        self._add_error("XCC-AOT-TYPE-0002", f"Unsupported annotation: {name}", owner)
        return AotType(name)

    def _add_error(self, code: str, message: str, node: ast.AST) -> None:
        self._diagnostics.append(
            AotDiagnostic(
                code,
                message,
                filename=self.summary.filename,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
            )
        )
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`:

```python
from xcc.aot.binder import bind_types
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType, AotTypeAnalysis

__all__ = (
    "AotClassInfo",
    "AotDiagnostic",
    "AotError",
    "AotFunctionInfo",
    "AotModule",
    "AotModuleSummary",
    "AotType",
    "AotTypeAnalysis",
    "bind_types",
    "check_subset",
    "parse_path",
    "parse_source",
)
```

- [ ] **Step 5: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot -v
```

Expected: all current AOT tests pass.

- [ ] **Step 6: Commit type binder**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/types.py src/xcc/aot/binder.py tests/test_aot.py
git commit -m "feat: bind AOT Python types"
```

## Task 5: Public Analysis API

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`
- Create: `/Users/tcztzy/GitHub/xcc/src/xcc/aot/analysis.py`
- Modify: `/Users/tcztzy/GitHub/xcc/tests/test_aot.py`

- [ ] **Step 1: Add failing public API tests**

Append this class to `/Users/tcztzy/GitHub/xcc/tests/test_aot.py` before the
`if __name__ == "__main__"` block:

```python
from xcc.aot import analyze_source


class AotAnalysisApiTests(unittest.TestCase):
    def test_analyze_source_returns_summary_and_types(self) -> None:
        source = "int64 = int\ndef f(value: int64) -> int64:\n    return value\n"
        analysis = analyze_source(source, filename="api.py")
        self.assertEqual(analysis.module.filename, "api.py")
        self.assertEqual(analysis.summary.functions, ("f",))
        self.assertEqual(analysis.types.functions["f"].return_type.name, "int64")

    def test_analyze_source_raises_first_stage_error(self) -> None:
        with self.assertRaises(AotError) as ctx:
            analyze_source("value = lambda x: x\n", filename="bad.py")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SUBSET-0001")
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot.AotAnalysisApiTests -v
```

Expected: import failure for `analyze_source`.

- [ ] **Step 3: Implement public analysis orchestration**

Create `/Users/tcztzy/GitHub/xcc/src/xcc/aot/analysis.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.binder import bind_types
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotTypeAnalysis


@dataclass(frozen=True)
class AotAnalysis:
    module: AotModule
    summary: AotModuleSummary
    types: AotTypeAnalysis


def analyze_source(source: str, *, filename: str = "<input>") -> AotAnalysis:
    module = parse_source(source, filename=filename)
    summary = check_subset(module)
    type_analysis = bind_types(summary, module)
    return AotAnalysis(module, summary, type_analysis)


def analyze_path(path: str | Path) -> AotAnalysis:
    module = parse_path(path)
    summary = check_subset(module)
    type_analysis = bind_types(summary, module)
    return AotAnalysis(module, summary, type_analysis)
```

Update `/Users/tcztzy/GitHub/xcc/src/xcc/aot/__init__.py`:

```python
from xcc.aot.analysis import AotAnalysis, analyze_path, analyze_source
from xcc.aot.binder import bind_types
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType, AotTypeAnalysis

__all__ = (
    "AotAnalysis",
    "AotClassInfo",
    "AotDiagnostic",
    "AotError",
    "AotFunctionInfo",
    "AotModule",
    "AotModuleSummary",
    "AotType",
    "AotTypeAnalysis",
    "analyze_path",
    "analyze_source",
    "bind_types",
    "check_subset",
    "parse_path",
    "parse_source",
)
```

- [ ] **Step 4: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot -v
```

Expected: all AOT tests pass.

- [ ] **Step 5: Commit public analysis API**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/analysis.py tests/test_aot.py
git commit -m "feat: add AOT analysis API"
```

## Task 6: Milestone 1 Status and Gates

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/CHANGELOG.md`

- [ ] **Step 1: Update current changelog status**

Add this bullet at the top of the `## Current` section in
`/Users/tcztzy/GitHub/xcc/CHANGELOG.md`:

```markdown
- Added the Milestone 1 AOT Python front-end skeleton under `src/xcc/aot/`:
  deterministic AOT diagnostics, Python source parsing through `ast.parse`,
  an XCC-Python subset checker for accepted and rejected syntax, a basic type
  binder for dataclass fields, function annotations, and width aliases, plus
  focused `tests/test_aot.py` coverage. This milestone intentionally emits no
  LLVM IR and does not change the existing `xcc` CLI path.
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run python -m unittest tests.test_aot -v
```

Expected: all AOT tests pass.

- [ ] **Step 3: Run full project tests**

Run:

```bash
uv run tox -e py311
```

Expected: full py311 suite passes with the repository's 100% coverage gate.

- [ ] **Step 4: Run handoff gates**

Run:

```bash
uv run tox -e lint
uv run tox -e type
```

Expected: lint and type gates pass.

- [ ] **Step 5: Commit Milestone 1 status**

Run:

```bash
git add CHANGELOG.md
git commit -m "docs: record AOT milestone 1 status"
```

## Final Review Checklist

- [ ] `tests/test_aot.py` covers diagnostics, parsing, subset accept/reject,
  type binding, and public analysis orchestration.
- [ ] No production XCC compiler path imports `xcc.aot` unless a caller uses the
  new package directly.
- [ ] Unsupported syntax uses deterministic diagnostics with stable codes.
- [ ] Width aliases are recognized only as ordinary Python assignments to `int`.
- [ ] No `from __future__ import annotations` was added.
- [ ] Runtime source still uses only Python standard library imports.
- [ ] `uv run tox -e py311`, `uv run tox -e lint`, and `uv run tox -e type`
  pass before handoff.

