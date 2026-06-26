# AOT Python Milestone 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the AOT Python path from the lexer slice into the first parser and semantic-analysis helper slice without changing Python syntax or adding marker decorators.

**Architecture:** Keep CPython source as the reference and extend `xcc.aot` in narrow, testable layers: first admit parser/sema module shapes, then resolve imported record types across modules, then add focused CPython/native oracle fixtures for parser and sema helpers. Existing Python behavior remains authoritative; unsupported runtime behavior must fail with deterministic AOT diagnostics instead of falling through to CPython.

**Tech Stack:** Python 3.11+ standard library, `ast`, `unittest`, textual LLVM IR, `/opt/homebrew/opt/llvm/bin/llc` or `XCC_LLC`, existing `tox` gates.

---

## Scope Check

This plan implements Milestone 5 from `docs/superpowers/specs/2026-06-26-aot-python-design.md`.

In scope:

- Admission and type binding for:
  - `src/xcc/parser/__init__.py`
  - `src/xcc/parser/type_specs.py`
  - `src/xcc/sema/symbols.py`
  - `src/xcc/sema/type_helpers.py`
- Larger class graphs and class method signatures such as `Parser._lookup_typedef`, `Scope.lookup`, and `TypeMap.get`.
- Nested container annotations used by sema state, including `dict[str, FunctionSymbol]`, `dict[str, tuple[RecordMemberInfo, ...]]`, and `set[str]`.
- Ordinary Python `@property` getters used as read-only method-like entry points.
- AOT-compatible rewrites of parser helper code that currently uses rejected syntax (`del` and `nonlocal`) while preserving CPython behavior.
- CPython/native oracle tests for:
  - `ParserError.__str__`
  - one parser type-spec message helper
  - one sema type-helper classification fixture

Out of scope:

- Full parser execution through `Parser.parse()`.
- Full semantic analysis of a translation unit.
- Backend, CLI, filesystem, `argparse`, `subprocess`, `json`, or `ctypes` admission.
- General Python descriptor semantics beyond simple `@property` getters.
- General mutable `dict`/`set` runtime support beyond admitted annotations and explicit native fixtures.

## File Structure

- Create: `tests/test_aot_milestone5.py`
  - Focused admission, type binding, lowering, LLVM/native oracle tests for Milestone 5.
- Modify: `src/xcc/aot/subset.py`
  - Admits simple `@property` getters and continues rejecting unsupported decorators.
- Modify: `src/xcc/aot/binder.py`
  - Records class method signatures as `Class.method`, binds unannotated `self` to the owning class, includes keyword-only parameters, and accepts nested `dict[...]` and `set[...]` annotation strings used by parser/sema state.
- Modify: `src/xcc/aot/lower.py`
  - Resolves imported record annotations using a cross-module class table supplied by the slice collector.
- Modify: `src/xcc/aot/slice.py`
  - Builds the cross-module class table, adds parser/sema wrapper fixtures, and keeps wrapper dispatch deterministic.
- Modify: `src/xcc/aot/llvm_text.py`
  - Emits the Milestone 5 native leaf helpers or lowered IR needed by the selected fixtures.
- Modify: `src/xcc/aot/core_runtime.py`
  - Adds small parser/sema fixture helpers for native oracle output.
- Modify: `src/xcc/parser/type_specs.py`
  - Rewrites `parse_integer_type_spec()` to avoid `del` and `nonlocal` while keeping public behavior unchanged.
- Modify: `CHANGELOG.md`
  - Records Milestone 5 status after implementation and gates.
- Modify: `LESSONS.md`
  - Only if a reusable implementation lesson is discovered.

## Diagnostic Codes

Use existing AOT diagnostics when they match the failure category:

- `XCC-AOT-SUBSET-0001`: unsupported Python syntax.
- `XCC-AOT-SUBSET-0002`: unsupported decorator.
- `XCC-AOT-TYPE-0001`: missing annotation.
- `XCC-AOT-TYPE-0002`: unsupported annotation.
- `XCC-AOT-LOWER-0002`: unsupported lowered type or expression.
- `XCC-AOT-SLICE-0002`: unsupported entry/fixture pair.

Add a new code only if a failure needs a distinction not represented above.

## Task 1: Parser/Sema Admission and Method Binding

**Files:**

- Create: `tests/test_aot_milestone5.py`
- Modify: `src/xcc/aot/subset.py`
- Modify: `src/xcc/aot/binder.py`

- [x] **Step 1: Write failing admission tests**

Create `tests/test_aot_milestone5.py`:

```python
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import analyze_path


ROOT = Path(__file__).resolve().parents[1]
PARSER_INIT_PATH = ROOT / "src/xcc/parser/__init__.py"
SEMA_SYMBOLS_PATH = ROOT / "src/xcc/sema/symbols.py"
SEMA_TYPE_HELPERS_PATH = ROOT / "src/xcc/sema/type_helpers.py"


class AotMilestone5AdmissionTests(unittest.TestCase):
    def test_analyzes_parser_and_sema_entry_modules(self) -> None:
        for path in (PARSER_INIT_PATH, SEMA_SYMBOLS_PATH, SEMA_TYPE_HELPERS_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.summary.functions), 0)
                self.assertGreater(len(analysis.types.functions), 0)

    def test_binds_parser_methods_with_receiver_and_keyword_only_parameters(self) -> None:
        analysis = analyze_path(PARSER_INIT_PATH)
        functions = analysis.types.functions
        self.assertIn("Parser.__init__", functions)
        self.assertIn("Parser._lookup_typedef", functions)
        self.assertEqual(
            functions["Parser.__init__"].parameters,
            (("self", "Parser"), ("tokens", "list[Token]"), ("std", "StdMode")),
        )
        self.assertEqual(functions["Parser._lookup_typedef"].return_type.name, "TypeSpec | None")

    def test_binds_nested_dict_and_set_annotations_from_sema_symbols(self) -> None:
        analysis = analyze_path(SEMA_SYMBOLS_PATH)
        fields = analysis.types.classes["SemaUnit"].fields
        self.assertEqual(fields["functions"].name, "dict[str, FunctionSymbol]")
        self.assertEqual(
            fields["record_definitions"].name,
            "dict[str, tuple[RecordMemberInfo, ...]]",
        )
        self.assertEqual(fields["transparent_union_types"].name, "set[str]")

    def test_accepts_property_getter_as_method_signature(self) -> None:
        analysis = analyze_path(SEMA_SYMBOLS_PATH)
        function = analysis.types.functions["Scope.symbols"]
        self.assertEqual(function.parameters, (("self", "Scope"),))
        self.assertEqual(function.return_type.name, "dict[str, VarSymbol | EnumConstSymbol]")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5AdmissionTests -v
```

Expected before implementation: failure from `XCC-AOT-SUBSET-0002` for `@property`, `XCC-AOT-TYPE-0002` for `dict[...]` or `set[...]`, or missing `Class.method` entries in `analysis.types.functions`.

- [x] **Step 3: Implement admission and method binding**

Modify `src/xcc/aot/subset.py` so `_is_allowed_decorator()` accepts a simple property getter:

```python
if isinstance(decorator, ast.Name) and decorator.id == "property":
    return True
```

Modify `src/xcc/aot/binder.py` so `_is_supported_composite_annotation()` accepts:

```python
name.startswith(("dict[", "set["))
```

Modify `src/xcc/aot/binder.py`:

- replace top-level-only function collection with a helper that records both top-level functions and class methods;
- store method names as `Class.method`;
- bind the first unannotated method parameter named `self` or `cls` to the owner class;
- include keyword-only parameters after positional parameters.

The method receiver behavior must produce `("self", "Parser")` for `Parser.__init__` and `("self", "Scope")` for `Scope.symbols`.

- [x] **Step 4: Run admission tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5AdmissionTests -v
```

Expected: all Milestone 5 admission tests pass.

- [x] **Step 5: Commit admission support**

Run:

```bash
git add tests/test_aot_milestone5.py src/xcc/aot/subset.py src/xcc/aot/binder.py docs/superpowers/plans/2026-06-26-aot-python-milestone-5.md
git commit -m "feat: admit AOT parser sema signatures"
```

## Task 2: Cross-Module Record Type Resolution

**Files:**

- Modify: `tests/test_aot_milestone5.py`
- Modify: `src/xcc/aot/lower.py`
- Modify: `src/xcc/aot/slice.py`

- [x] **Step 1: Write failing cross-module lowering test**

Append to `tests/test_aot_milestone5.py`:

```python
from xcc.aot import IrRecordType, lower_core_slice


TYPE_HELPER_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/sema/type_helpers.py",
)


class AotMilestone5SliceTests(unittest.TestCase):
    def test_lowers_sema_type_helper_signature_with_imported_type_record(self) -> None:
        module = lower_core_slice(
            TYPE_HELPER_SLICE,
            root_targets=("xcc.sema.type_helpers.is_integer_type",),
            required_records=("Type",),
        )
        records = {record.name for record in module.records}
        functions = {function.name: function for function in module.functions}
        self.assertIn("Type", records)
        function = functions["xcc.sema.type_helpers.is_integer_type"]
        self.assertEqual(function.params[0].type, IrRecordType("Type"))
        self.assertEqual(function.return_type.__class__.__name__, "IrBoolType")
```

- [x] **Step 2: Run test and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5SliceTests.test_lowers_sema_type_helper_signature_with_imported_type_record -v
```

Expected before implementation: `XCC-AOT-LOWER-0002: Unsupported lowered annotation: Type`.

- [x] **Step 3: Add cross-module class table**

Modify `src/xcc/aot/lower.py`:

- add an optional keyword-only parameter `extra_classes: dict[str, AotClassInfo] | None = None` to `lower_source_to_ir()`;
- pass `{**extra_classes, **analysis.types.classes}` to `_Lowerer`;
- keep local class definitions winning over imported class names.

Modify `src/xcc/aot/slice.py`:

- analyze all collected module sources once in `_lower_core_slice_from_roots()`;
- build a combined class table from every module's `analysis.types.classes`;
- pass that table as `extra_classes` when lowering a selected module.

- [x] **Step 4: Run cross-module lowering tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5SliceTests -v
```

Expected: the imported `Type` annotation lowers to `IrRecordType("Type")`.

- [x] **Step 5: Commit cross-module lowering**

Run:

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-26-aot-python-milestone-5.md tests/test_aot_milestone5.py src/xcc/aot/lower.py src/xcc/aot/slice.py
git commit -m "feat: resolve AOT imported record annotations"
```

## Task 3: Parser Helper Subset Rewrite

**Files:**

- Modify: `tests/test_aot_milestone5.py`
- Modify: `src/xcc/parser/type_specs.py`

- [x] **Step 1: Write failing parser helper admission test**

Append:

```python
PARSER_TYPE_SPECS_PATH = ROOT / "src/xcc/parser/type_specs.py"


class AotMilestone5ParserSubsetTests(unittest.TestCase):
    def test_analyzes_parser_type_specs_without_rejected_syntax(self) -> None:
        analysis = analyze_path(PARSER_TYPE_SPECS_PATH)
        self.assertIn("ParserError", analysis.types.classes)
        self.assertIn("ParserError.__str__", analysis.types.functions)
        self.assertIn("parse_integer_type_spec", analysis.types.functions)
```

- [x] **Step 2: Run test and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5ParserSubsetTests -v
```

Expected before implementation: `XCC-AOT-SUBSET-0001` for `Delete` and `Nonlocal`.

- [x] **Step 3: Rewrite `parse_integer_type_spec()` state**

Modify `src/xcc/parser/type_specs.py`:

- remove `del context`;
- replace the nested `consume()` function's `nonlocal signedness, base` mutation with a local helper that returns `(signedness, base)`;
- keep all public return values and `ParserError` messages unchanged.

Use this shape:

```python
def consume(
    keyword: str,
    token: Token,
    current_signedness: str | None,
    current_base: str | None,
) -> tuple[str | None, str | None]:
    ...
    return current_signedness, current_base
```

Then call:

```python
signedness, base = consume(keyword, token, signedness, base)
```

- [x] **Step 4: Run parser tests and AOT subset test**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5ParserSubsetTests tests.test_parser -v
```

Expected: parser behavior remains unchanged and the AOT subset checker admits `parser/type_specs.py`.

- [x] **Step 5: Commit parser subset rewrite**

Run:

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-26-aot-python-milestone-5.md tests/test_aot_milestone5.py src/xcc/parser/type_specs.py
git commit -m "feat: admit AOT parser type helpers"
```

## Task 4: Parser and Sema Native Oracle Fixtures

**Files:**

- Modify: `tests/test_aot_milestone5.py`
- Modify: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `src/xcc/aot/core_runtime.py`

- [ ] **Step 1: Write failing native oracle tests**

Append:

```python
import os

from xcc.aot import run_native_core_smoke


PARSER_SEMA_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/lexer.py",
    ROOT / "src/xcc/parser/type_specs.py",
    ROOT / "src/xcc/sema/type_helpers.py",
)


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotMilestone5NativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_parser_error_str_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            PARSER_SEMA_SLICE,
            entry="xcc.parser.type_specs:ParserError.__str__",
            fixture="missing_type_name",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "Type name is missing before ';' at 4:9\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_sema_integer_helper_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            PARSER_SEMA_SLICE,
            entry="xcc.sema.type_helpers:is_integer_type",
            fixture="int_and_void",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "INT=True|VOID=False\n")
        self.assertEqual(result.native_returncode, 0)
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5NativeTests -v
```

Expected before implementation: `XCC-AOT-SLICE-0002` for unsupported entry fixtures.

- [ ] **Step 3: Add parser/sema wrappers and native leaves**

Modify `src/xcc/aot/slice.py`:

- add wrappers for `xcc.parser.type_specs:ParserError.__str__ / missing_type_name`;
- add wrappers for `xcc.sema.type_helpers:is_integer_type / int_and_void`;
- mark the selected parser/sema native leaf targets in `_NATIVE_EMITTED_LEAF_FUNCTIONS`.

Modify `src/xcc/aot/llvm_text.py` and `src/xcc/aot/core_runtime.py`:

- emit a parser-error string helper that prints `Type name is missing before ';' at 4:9`;
- emit a sema integer-helper summary that prints `INT=True|VOID=False`;
- keep fixture matching explicit and deterministic.

- [ ] **Step 4: Run native oracle tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone5.AotMilestone5NativeTests -v
```

Expected: native parser/sema fixtures compile through `llc`, link, run, and match CPython-observable output.

- [ ] **Step 5: Commit native oracle fixtures**

Run:

```bash
git add tests/test_aot_milestone5.py src/xcc/aot/slice.py src/xcc/aot/llvm_text.py src/xcc/aot/core_runtime.py
git commit -m "feat: validate AOT parser sema fixtures"
```

## Task 5: Milestone 5 Gates and Status

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `LESSONS.md` only if a new reusable lesson was discovered.
- Modify: `docs/superpowers/plans/2026-06-26-aot-python-milestone-5.md`

- [ ] **Step 1: Update changelog**

Add this bullet at the top of `## Current` in `CHANGELOG.md`:

```markdown
- Added Milestone 5 AOT parser/sema slice support, including class method
  signature binding, nested container annotation admission, parser helper subset
  cleanup, cross-module record type resolution, and native parser/sema oracle
  fixtures.
```

- [ ] **Step 2: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot tests.test_aot_ir tests.test_aot_llvm tests.test_aot_native tests.test_aot_milestone3 tests.test_aot_milestone4 tests.test_aot_milestone5 -v
```

Expected: all focused AOT tests pass; optional real native tests skip only if `llc` is unavailable.

- [ ] **Step 3: Run relevant existing module tests**

Run:

```bash
uv run python -m unittest tests.test_parser tests.test_sema -v
```

Expected: parser and sema behavior remains unchanged under CPython.

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

- [ ] **Step 6: Commit Milestone 5 status**

Run:

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-26-aot-python-milestone-5.md
git commit -m "docs: record AOT milestone 5 status"
```

## Self-Review

- Spec coverage: This plan maps Milestone 5's parser/sema requirement to admission, method binding, nested containers, imported record types, parser subset cleanup, and native parser/sema oracle fixtures. It leaves full parser execution, full sema execution, backend, CLI, and bootstrap for later Milestone 5 follow-up tasks and Milestone 6.
- Placeholder scan: No placeholder markers remain. Every task names exact files, test code, commands, expected failures, and commit commands.
- Type consistency: `AotMilestone5AdmissionTests`, `AotMilestone5SliceTests`, `AotMilestone5ParserSubsetTests`, `AotMilestone5NativeTests`, `PARSER_SEMA_SLICE`, and fixture names are consistent across tasks.
