# AOT Python Milestone 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile and validate enough of `src/xcc/ast.py` and `src/xcc/lexer.py` to run representative lexer fixtures through native AOT code and compare token streams with CPython.

**Architecture:** Extend the independent `xcc.aot` pipeline from the Milestone 3 core slice to a front-end slice. The first implementation admits and binds the `ast.py` and `lexer.py` module shapes, then adds a small enum/list/string runtime surface and native wrappers that exercise `translate_source`, `lex`, and selected lexer error paths without adding any non-Python syntax or decorators.

**Tech Stack:** Python 3.11+ standard library, `ast`, `unittest`, textual LLVM IR, `/opt/homebrew/opt/llvm/bin/llc` or `XCC_LLC`, existing `tox` gates.

---

## Scope Check

This plan implements Milestone 4 from `docs/superpowers/specs/2026-06-26-aot-python-design.md`.

In scope:

- `src/xcc/ast.py`
- `src/xcc/lexer.py`
- AOT subset/type admission for:
  - forward-reference annotations such as `"Expr | None"` and `"StringLiteral"`
  - `list[...]` annotations used by AST node fields and lexer return types
  - `field(default_factory=list)` dataclass fields used by `TranslationUnit`
  - simple `Enum` classes with `auto()` values used by `TokenKind`
  - regex constants as compile-time lexer classification shims, not as a general regex runtime
- CPython/native oracle tests for:
  - `translate_source`
  - `lex` on a representative C snippet
  - `lex_pp(..., header_names=True)` for header-name tokenization
  - one deterministic lexer error path

Out of scope:

- Parser, sema, and backend compilation.
- A general Python `re` runtime.
- General `Enum` metaclass compatibility.
- Arbitrary list mutation beyond lexer token accumulation and fixed helper fixtures.
- Full `Lexer` object model coverage for every existing lexer unit test.

## File Structure

- Modify: `src/xcc/aot/binder.py`
  - Accepts Milestone 4 annotation shapes and records enum-like classes.
- Modify: `src/xcc/aot/types.py`
  - Adds builtin/shim type names used by `ast.py` and `lexer.py`.
- Modify: `src/xcc/aot/subset.py`
  - Admits the stdlib shims used by Milestone 4 and rejects unsupported regex/runtime calls deterministically.
- Modify: `src/xcc/aot/slice.py`
  - Adds approved wrappers for AST/lexer fixtures and expands core slice collection tests.
- Modify: `src/xcc/aot/ir.py`
  - Adds only the list/enum/string operations needed by lexer fixtures, if current call IR is insufficient.
- Modify: `src/xcc/aot/lower.py`
  - Lowers the concrete Milestone 4 operations used by wrappers and selected lexer helpers.
- Modify: `src/xcc/aot/llvm_text.py`
  - Emits the added IR and calls minimal runtime helpers.
- Modify: `src/xcc/aot/core_runtime.py`
  - Adds small list/token rendering helpers if needed by native oracle output.
- Modify: `src/xcc/aot/native.py`
  - Reuses `run_native_core_smoke()` or adds a named wrapper fixture path for lexer slice tests.
- Create: `tests/test_aot_milestone4.py`
  - Focused tests for admission, binding, subset checks, lowering, LLVM emission, and native lexer oracle behavior.
- Modify: `CHANGELOG.md`
  - Records Milestone 4 status after implementation and gates.
- Modify: `LESSONS.md`
  - Only if a reusable lesson is learned while implementing.

## Diagnostic Codes

Use existing AOT diagnostics when they already match the failure category. Add these only when a new distinction is needed:

- `XCC-AOT-TYPE-0006`: unsupported enum or dataclass default shape.
- `XCC-AOT-SUBSET-0004`: unsupported Milestone 4 stdlib shim usage.
- `XCC-AOT-RUNTIME-0002`: unsupported lexer runtime helper request.

## Task 1: AST/Lexer Admission and Type Binding

**Files:**

- Create: `tests/test_aot_milestone4.py`
- Modify: `src/xcc/aot/types.py`
- Modify: `src/xcc/aot/binder.py`

- [ ] **Step 1: Write failing admission tests**

Create `tests/test_aot_milestone4.py`:

```python
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, analyze_path


ROOT = Path(__file__).resolve().parents[1]
AST_PATH = ROOT / "src/xcc/ast.py"
LEXER_PATH = ROOT / "src/xcc/lexer.py"


class AotMilestone4AdmissionTests(unittest.TestCase):
    def test_analyzes_ast_and_lexer_modules(self) -> None:
        for path in (AST_PATH, LEXER_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.summary.classes), 0)
                self.assertGreater(len(analysis.types.classes), 0)

    def test_binds_lexer_token_kind_enum_and_token_dataclass(self) -> None:
        analysis = analyze_path(LEXER_PATH)
        self.assertIn("TokenKind", analysis.types.classes)
        self.assertIn("Token", analysis.types.classes)
        self.assertEqual(analysis.types.classes["Token"].fields["line"].name, "int")

    def test_binds_ast_forward_refs_lists_and_default_factories(self) -> None:
        analysis = analyze_path(AST_PATH)
        self.assertIn("TranslationUnit", analysis.types.classes)
        fields = analysis.types.classes["TranslationUnit"].fields
        self.assertEqual(fields["functions"].name, "list['FunctionDef']")
        self.assertEqual(fields["declarations"].name, "list['Stmt']")
        self.assertIn("TypeSpec", analysis.types.classes)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4AdmissionTests -v
```

Expected: failures like `Unsupported annotation: list['FunctionDef']`, `Unsupported annotation: Enum`, and `Unsupported annotation: list[Token]`.

- [ ] **Step 3: Add Milestone 4 builtin/shim types**

Modify `src/xcc/aot/types.py`:

```python
_BUILTIN_TYPES = {
    "Enum",
    "NoReturn",
    "ValueError",
    "bool",
    "int",
    "None",
    "object",
    "str",
}
```

Keep existing width aliases unchanged.

- [ ] **Step 4: Accept project-list and direct class annotations**

Modify `_is_supported_composite_annotation()` in `src/xcc/aot/binder.py`:

```python
def _is_supported_composite_annotation(name: str) -> bool:
    return (
        name.startswith(("tuple[", "Literal["))
        or _is_supported_list_annotation(name)
        or " | " in name
        or name[:1].isupper()
    )


def _is_supported_list_annotation(name: str) -> bool:
    if not name.startswith("list[") or not name.endswith("]"):
        return False
    element = name[5:-1].strip("\"'")
    return element[:1].isupper()
```

This deliberately admits forward-reference class names such as `TypeSpec` and `StringLiteral`, plus project-object lists such as `list[Token]` and `list['Stmt']`, for binding metadata only. It must continue rejecting broad builtin lists such as `list[int]`; runtime lowering still has to reject unsupported object operations.

- [ ] **Step 5: Record enum-like classes without fields**

Modify `_collect_classes()` in `src/xcc/aot/binder.py` so enum classes are accepted:

```python
    def _collect_classes(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            bases = tuple(annotation_name(base) for base in statement.bases)
            fields: dict[str, AotType] = {}
            for child in statement.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields[child.target.id] = self._resolve_annotation(child.annotation, child)
            self.classes[statement.name] = AotClassInfo(statement.name, fields, bases)
```

If the existing implementation already matches this shape, leave it unchanged; the important behavior is that `class TokenKind(Enum): KEYWORD = auto()` creates an `AotClassInfo` and does not require enum members as dataclass fields.

- [ ] **Step 6: Run admission tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4AdmissionTests -v
```

Expected: tests pass.

- [ ] **Step 7: Commit admission foundation**

Run:

```bash
git add src/xcc/aot/types.py src/xcc/aot/binder.py tests/test_aot_milestone4.py
git commit -m "feat: admit AOT AST and lexer modules"
```

## Task 2: Subset Checker Shims for Enum, Regex Constants, and Cast

**Files:**

- Modify: `tests/test_aot_milestone4.py`
- Modify: `src/xcc/aot/subset.py`

- [ ] **Step 1: Write failing subset tests**

Append:

```python
from xcc.aot import analyze_source


class AotMilestone4SubsetTests(unittest.TestCase):
    def test_accepts_enum_auto_and_compile_time_regex_constants(self) -> None:
        source = (
            "import re\n"
            "from enum import Enum, auto\n"
            "R = re.compile(r'^[0-9]+$')\n"
            "class Kind(Enum):\n"
            "    VALUE = auto()\n"
        )
        analysis = analyze_source(source, filename="enum_regex.py")
        self.assertIn("Kind", analysis.summary.classes)
        self.assertIn("re", analysis.summary.imports)

    def test_rejects_runtime_regex_search_in_milestone4(self) -> None:
        source = "import re\ndef f(value: str) -> bool:\n    return re.search('x', value) is not None\n"
        with self.assertRaises(AotError) as ctx:
            analyze_source(source, filename="bad_regex.py")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SUBSET-0004")
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4SubsetTests -v
```

Expected: the runtime regex rejection test currently passes through or fails with a less specific diagnostic.

- [ ] **Step 3: Add explicit shim call classification**

Modify `src/xcc/aot/subset.py`:

```python
_ALLOWED_STDLIB_SHIM_CALLS = {"auto", "cast", "field", "re.compile"}
_REJECTED_STDLIB_SHIM_CALLS = {"re.fullmatch", "re.match", "re.search"}
```

Update `visit_Call()`:

```python
    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in _DYNAMIC_CALLS:
            self._add_error(
                "XCC-AOT-SUBSET-0003",
                f"Unsupported dynamic call: {name}",
                node,
            )
        elif name in _REJECTED_STDLIB_SHIM_CALLS:
            self._add_error(
                "XCC-AOT-SUBSET-0004",
                f"Unsupported runtime stdlib shim call: {name}",
                node,
            )
        self.generic_visit(node)
```

Update `_call_name()`:

```python
def _call_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        receiver = _call_name(expr.value)
        if receiver is None:
            return expr.attr
        return f"{receiver}.{expr.attr}"
    return None
```

- [ ] **Step 4: Run subset tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4SubsetTests -v
```

Expected: tests pass.

- [ ] **Step 5: Commit subset shim checks**

Run:

```bash
git add src/xcc/aot/subset.py tests/test_aot_milestone4.py
git commit -m "feat: add AOT lexer stdlib shim checks"
```

## Task 3: Lexer Slice Inputs and Wrappers

**Files:**

- Modify: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/__init__.py` only if a new public helper is needed.
- Modify: `tests/test_aot_milestone4.py`

- [ ] **Step 1: Write failing wrapper tests**

Append:

```python
from xcc.aot import collect_slice_inputs, core_entry_wrapper, lower_core_slice


LEXER_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/diag.py",
    ROOT / "src/xcc/options.py",
    ROOT / "src/xcc/ast.py",
    ROOT / "src/xcc/lexer.py",
)


class AotMilestone4SliceTests(unittest.TestCase):
    def test_collects_frontend_slice_modules(self) -> None:
        modules = collect_slice_inputs(LEXER_SLICE)
        self.assertEqual(
            [module.name for module in modules],
            ["xcc.ast", "xcc.diag", "xcc.lexer", "xcc.options", "xcc.types"],
        )

    def test_builds_lexer_entry_wrappers(self) -> None:
        translate = core_entry_wrapper("xcc.lexer:translate_source", "trigraph_splice")
        self.assertEqual(translate.name, "__xcc_aot_core_entry")
        lexer = core_entry_wrapper("xcc.lexer:lex", "simple_declaration")
        self.assertEqual(lexer.name, "__xcc_aot_core_entry")
        header = core_entry_wrapper("xcc.lexer:lex_pp", "header_name")
        self.assertEqual(header.name, "__xcc_aot_core_entry")
        error = core_entry_wrapper("xcc.lexer:lex_error", "unterminated_string")
        self.assertEqual(error.name, "__xcc_aot_core_entry")

    def test_lowers_frontend_slice_to_module_graph(self) -> None:
        module = lower_core_slice(LEXER_SLICE)
        names = {function.name for function in module.functions}
        self.assertIn("xcc.lexer.translate_source", names)
        self.assertIn("xcc.lexer.lex", names)
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4SliceTests -v
```

Expected: wrapper fixture tests fail with `XCC-AOT-SLICE-0002`; lowering may still fail on unsupported syntax until Tasks 1 and 2 are complete.

- [ ] **Step 3: Add wrapper cases**

Modify `core_entry_wrapper()` in `src/xcc/aot/slice.py`:

```python
    if entry == "xcc.lexer:translate_source" and fixture == "trigraph_splice":
        return _lexer_translate_source_wrapper()
    if entry == "xcc.lexer:lex" and fixture == "simple_declaration":
        return _lexer_lex_simple_declaration_wrapper()
    if entry == "xcc.lexer:lex_pp" and fixture == "header_name":
        return _lexer_header_name_wrapper()
    if entry == "xcc.lexer:lex_error" and fixture == "unterminated_string":
        return _lexer_unterminated_string_wrapper()
```

Add wrapper functions that print deterministic string summaries:

```python
def _lexer_translate_source_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(
                IrCall(
                    "xcc.lexer.translate_source",
                    (IrConstString("int??=x\\\\\n=1;"),),
                    IrStringType(),
                )
            ),
            IrReturn(IrConstInt(0, int32)),
        ),
    )
```

For token fixtures, prefer wrappers that call dedicated lowered helper functions added in Task 6, such as `xcc.lexer._aot_token_summary_for_source`, rather than trying to print raw list objects.

- [ ] **Step 4: Run wrapper tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4SliceTests -v
```

Expected: wrapper construction passes. Full native behavior waits for later tasks.

- [ ] **Step 5: Commit wrapper foundation**

Run:

```bash
git add src/xcc/aot/slice.py tests/test_aot_milestone4.py
git commit -m "feat: add AOT lexer slice wrappers"
```

## Task 4: Minimal String/Loop Lowering for `translate_source`

**Files:**

- Modify: `tests/test_aot_milestone4.py`
- Modify: `src/xcc/aot/lower.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `src/xcc/aot/core_runtime.py`

- [ ] **Step 1: Write failing native translate test**

Append:

```python
import os
from xcc.aot import run_native_core_smoke


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotMilestone4NativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_translate_source_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:translate_source",
            fixture="trigraph_splice",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "int#x=1;\n")
        self.assertEqual(result.native_returncode, 0)
```

- [ ] **Step 2: Run native translate test and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4NativeTests.test_native_translate_source_matches_cpython -v
```

Expected: failure because `while`, string indexing/slicing, list append, or `"".join` lowering is missing.

- [ ] **Step 3: Lower concrete while-loop and string indexing shapes**

Extend `src/xcc/aot/ir.py` only if needed with `IrWhile`, `IrBreak`, or string index operations. Then update `src/xcc/aot/lower.py` for the exact `translate_source`, `_replace_trigraphs`, and `_splice_lines` shapes:

- `while i < length:`
- `if source[i] == ...`
- `out.append(...)`
- `i += N`
- `"".join(out)`

If the current generic lowering would pull in too much Python list behavior, add a native-specialized helper path for `xcc.lexer.translate_source`, matching the existing `xcc.types.Type.__str__` specialization pattern. Keep the Python source unchanged.

- [ ] **Step 4: Add minimal runtime helpers**

Add helpers only as needed:

- string length
- single-byte string index
- string equality against one-character constants
- growable byte buffer append
- byte buffer join

Runtime helpers must live in `src/xcc/aot/core_runtime.py` and be exercised by tests.

- [ ] **Step 5: Run translate native test**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4NativeTests.test_native_translate_source_matches_cpython -v
```

Expected: test passes when `llc` is present.

- [ ] **Step 6: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot_llvm tests.test_aot_milestone3 tests.test_aot_milestone4 -v
```

Expected: tests pass.

- [ ] **Step 7: Commit translate native behavior**

Run:

```bash
git add src/xcc/aot/ir.py src/xcc/aot/lower.py src/xcc/aot/llvm_text.py src/xcc/aot/core_runtime.py tests/test_aot_milestone4.py
git commit -m "feat: validate AOT lexer source translation"
```

## Task 5: Token Summary Fixture for `lex`

**Files:**

- Modify: `src/xcc/lexer.py` only if adding ordinary helper functions is the smallest CPython-compatible surface.
- Modify: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/lower.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `tests/test_aot_milestone4.py`

- [ ] **Step 1: Write failing CPython/native token test**

Append:

```python
class AotMilestone4NativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_lex_simple_declaration_matches_cpython_summary(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:lex",
            fixture="simple_declaration",
            llc=_real_llc(),
        )
        self.assertEqual(
            result.native_stdout,
            "KEYWORD:int:1:1|IDENT:main:1:5|PUNCTUATOR:(:1:9|PUNCTUATOR:):1:10|"
            "PUNCTUATOR:{:1:12|KEYWORD:return:1:14|INT_CONST:0:1:21|"
            "PUNCTUATOR:;:1:22|PUNCTUATOR:}:1:24|EOF:None:1:25\n",
        )
        self.assertEqual(result.native_returncode, 0)
```

- [ ] **Step 2: Run token test and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4NativeTests.test_native_lex_simple_declaration_matches_cpython_summary -v
```

Expected: failure because token list rendering and enough `Lexer.tokenize` lowering are missing.

- [ ] **Step 3: Add CPython-compatible token summary helper if needed**

If lowering raw list-of-Token printing would create too much runtime surface, add this ordinary helper to `src/xcc/lexer.py`:

```python
def summarize_tokens(tokens: list[Token]) -> str:
    return "|".join(
        f"{token.kind.name}:{token.lexeme}:{token.line}:{token.column}" for token in tokens
    )
```

This is normal Python, uses no new syntax, and is useful for deterministic tests. If generator expression lowering remains too broad, use an explicit loop:

```python
def summarize_tokens(tokens: list[Token]) -> str:
    parts: list[str] = []
    for token in tokens:
        parts.append(f"{token.kind.name}:{token.lexeme}:{token.line}:{token.column}")
    return "|".join(parts)
```

- [ ] **Step 4: Complete concrete lexer lowering**

Lower or specialize only the lexer operations needed by `lex("int main() { return 0; }")`:

- class construction for `Lexer` and `Token`
- `while True`
- `break`/`continue`
- list append of Token records
- `self._skip_whitespace_and_comments()`
- `_eof`, `_peek`, `_advance`
- keyword/identifier classification
- integer number classification for `0`
- punctuator reading for `(`, `)`, `{`, `}`, `;`
- enum value name rendering for summary output

Use deterministic `XCC-AOT-LOWER-*` diagnostics for any unsupported branch that is not part of this fixture.

- [ ] **Step 5: Run token native test**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4NativeTests.test_native_lex_simple_declaration_matches_cpython_summary -v
```

Expected: test passes when `llc` is present.

- [ ] **Step 6: Commit token fixture**

Run:

```bash
git add src/xcc/lexer.py src/xcc/aot/slice.py src/xcc/aot/lower.py src/xcc/aot/llvm_text.py tests/test_aot_milestone4.py
git commit -m "feat: validate AOT lexer token fixture"
```

## Task 6: Header Names and Lexer Error Path

**Files:**

- Modify: `tests/test_aot_milestone4.py`
- Modify: `src/xcc/aot/slice.py`
- Modify: `src/xcc/aot/lower.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `src/xcc/aot/core_runtime.py`

- [ ] **Step 1: Add failing header and error oracle tests**

Append:

```python
class AotMilestone4NativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_lex_pp_header_name_matches_cpython_summary(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:lex_pp",
            fixture="header_name",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "HEADER_NAME:<stdio.h>:1:1|EOF:None:1:10\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_lexer_error_matches_cpython_message(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:lex_error",
            fixture="unterminated_string",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_returncode, 2)
        self.assertIn("Unterminated string literal at 1:2", result.native_stdout)
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4NativeTests -v
```

Expected: the new tests fail until header-name and error lowering/runtime status handling exist.

- [ ] **Step 3: Add header-name fixture support**

Lower or specialize only:

- `lex_pp(source, header_names=True)`
- `Lexer(..., mode="preprocessor", header_names=True)`
- `_maybe_read_header_name` for `<stdio.h>`

- [ ] **Step 4: Add lexer error status support**

Lower `LexerError` construction/raise for the fixture to:

- print the CPython-compatible exception message
- return native process status `2`

Do not implement tracebacks.

- [ ] **Step 5: Run native lexer tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone4.AotMilestone4NativeTests -v
```

Expected: all Milestone 4 native tests pass when `llc` is present.

- [ ] **Step 6: Commit header/error fixture behavior**

Run:

```bash
git add src/xcc/aot/slice.py src/xcc/aot/lower.py src/xcc/aot/llvm_text.py src/xcc/aot/core_runtime.py tests/test_aot_milestone4.py
git commit -m "feat: validate AOT lexer header and error fixtures"
```

## Task 7: Milestone 4 Gates and Status

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `LESSONS.md` only if a new reusable lesson was discovered while implementing.

- [ ] **Step 1: Update changelog**

Add this bullet at the top of `## Current` in `CHANGELOG.md`:

```markdown
- Added Milestone 4 AOT lexer slice support for `ast.py` and `lexer.py`,
  including annotation admission, enum/list/dataclass-default shims, native
  `translate_source` and lexer token/error oracle fixtures, and focused tests
  that compare CPython behavior with native binaries.
```

- [ ] **Step 2: Run focused AOT tests**

Run:

```bash
uv run python -m unittest tests.test_aot tests.test_aot_ir tests.test_aot_llvm tests.test_aot_native tests.test_aot_milestone3 tests.test_aot_milestone4 -v
```

Expected: all focused AOT tests pass; optional real native tests skip only if `llc` is unavailable.

- [ ] **Step 3: Run relevant existing module tests**

Run:

```bash
uv run python -m unittest tests.test_lexer tests.test_frontend -v
```

Expected: existing CPython behavior remains unchanged.

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

- [ ] **Step 6: Commit Milestone 4 status**

Run:

```bash
git add CHANGELOG.md LESSONS.md
git commit -m "docs: record AOT milestone 4 status"
```

## Self-Review

- Spec coverage: This plan maps Milestone 4's `ast.py`/`lexer.py` requirement to admission, shim checks, native source translation, token summary, header-name, and error fixtures. It intentionally leaves parser/sema/backend and general regex/runtime compatibility for later milestones.
- Placeholder scan: No placeholder markers or unspecified test steps remain. Each task includes concrete files, test code, commands, expected failures, and commit points.
- Type consistency: `LEXER_SLICE`, `AotMilestone4NativeTests`, `summarize_tokens`, wrapper entry names, and fixture names are consistent across tasks.
