# AOT Python Milestone 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing AOT Python track into a native bootstrap path for XCC while keeping every source file valid CPython 3.11+ Python and avoiding marker syntax or decorators.

**Architecture:** Finish Milestone 6 in two layers. First, make every `src/xcc` module pass deterministic AOT subset/type admission and keep that as a regression gate. Then grow the native lowering and bootstrap harness from the existing CPython/native oracle path until a generated native `xcc` executable can compile the project inputs needed for self-host validation.

**Tech Stack:** Python 3.11+ standard library, `ast`, `dataclasses`, textual LLVM IR, `/opt/homebrew/opt/llvm/bin/llc` or `XCC_LLC`, existing `unittest` and `tox` gates.

---

## Scope Check

This plan implements Milestone 6 from `docs/superpowers/specs/2026-06-26-aot-python-design.md`.

In scope:

- AOT admission for every Python module under `src/xcc`.
- Source cleanup for rejected dynamic Python constructs already present in XCC source, such as runtime reflection, lambdas, and `nonlocal` state rebinding.
- A bootstrap source graph that records all modules needed by the native `xcc` executable.
- Native lowering and runtime shims for the CLI/front-end/backend path required by bootstrap.
- A native executable build helper that uses textual LLVM IR and `llc`.
- Self-host validation that runs the generated native `xcc` without the CPython runtime.

Out of scope:

- Supporting arbitrary Python packages or the full CPython object model.
- Adding marker decorators, pragmas, comment directives, or non-Python syntax.
- Adding non-stdlib runtime dependencies to XCC source.
- Claiming final bootstrap completion before the generated native executable has been run against the self-host inputs.

## File Structure

- Modify: `tests/test_aot_milestone6.py`
  - Holds all-src admission regression tests and targeted Milestone 6 source-shape tests.
- Modify: `src/xcc/aarch64_asm.py`
  - Removes remaining admission blockers from the AArch64 backend by replacing dataclass reflection and rebinding closures with explicit dispatch/state.
- Modify: `tests/test_aarch64_asm.py`
  - Adds focused coverage for explicit AArch64 AST child traversal.
- Create: `src/xcc/aot/bootstrap.py`
  - Owns bootstrap source discovery, admission reporting, bootstrap entry planning, and native build orchestration.
- Create: `tests/test_aot_bootstrap.py`
  - Tests bootstrap source graph, admission reports, native command planning, and final self-host harness behavior.
- Modify: `src/xcc/aot/slice.py`
  - Reuses and extends multi-module graph collection for bootstrap roots.
- Modify: `src/xcc/aot/lower.py`
  - Lowers the additional Python subset forms used by the bootstrap-reachable CLI/front-end/backend path.
- Modify: `src/xcc/aot/llvm_text.py`
  - Emits added IR forms and bootstrap entry wrappers as textual LLVM IR.
- Modify: `src/xcc/aot/core_runtime.py`
  - Adds minimal runtime helpers required by bootstrap-reachable objects and strings.
- Modify: `src/xcc/aot/native.py`
  - Adds native executable build helpers reusable by bootstrap validation.
- Modify: `CHANGELOG.md`
  - Records concrete Milestone 6 progress after each verified slice.
- Modify: `LESSONS.md`
  - Only when a reusable implementation lesson is discovered.

## Diagnostic Codes

Use existing AOT diagnostics when they match the failure category. Add these only when a new distinction is required:

- `XCC-AOT-BOOTSTRAP-0001`: bootstrap source graph cannot include a requested module.
- `XCC-AOT-BOOTSTRAP-0002`: bootstrap entry point or wrapper cannot be built from lowered symbols.
- `XCC-AOT-BOOTSTRAP-0003`: native bootstrap executable command failed.
- `XCC-AOT-RUNTIME-0003`: unsupported bootstrap runtime helper request.

## Task 1: Freeze All-Source Admission

**Files:**

- Modify: `tests/test_aot_milestone6.py`
- Modify: `CHANGELOG.md`

- [x] **Step 1: Add the all-source admission regression test**

Add this method to `AotMilestone6AdmissionTests` in `tests/test_aot_milestone6.py`:

```python
    def test_all_src_xcc_modules_are_aot_admitted(self) -> None:
        failures: list[str] = []
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            with self.subTest(path=path.relative_to(ROOT)):
                try:
                    analyze_path(path)
                except Exception as exc:
                    failures.append(f"{path.relative_to(ROOT)}: {exc}")
        self.assertEqual([], failures)
```

- [x] **Step 2: Run the focused test and verify it fails before the final cleanup**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone6.AotMilestone6AdmissionTests.test_all_src_xcc_modules_are_aot_admitted -v
```

Expected before cleanup: the test reports any remaining modules rejected by the AOT subset or type binder. Expected after this milestone's admission cleanup: the test passes for every module under `src/xcc`.

- [x] **Step 3: Record the admission target**

Add a `CHANGELOG.md` current entry sentence after the existing Milestone 6 admission status:

```markdown
  The Milestone 6 test gate now includes an all-`src/xcc` admission regression
  that analyzes every Python source file instead of relying on an ad hoc probe.
```

- [x] **Step 4: Run the full Milestone 6 admission suite**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone6 -v
```

Expected: all Milestone 6 admission tests pass.

- [x] **Step 5: Commit all-source admission gate**

Run:

```bash
git add tests/test_aot_milestone6.py CHANGELOG.md
git commit -m "test: gate AOT all-source admission"
```

## Task 2: Admit the AArch64 Backend

**Files:**

- Modify: `src/xcc/aarch64_asm.py`
- Modify: `tests/test_aarch64_asm.py`
- Modify: `tests/test_aot_milestone6.py`
- Modify: `CHANGELOG.md`

- [x] **Step 1: Add the focused AArch64 admission assertion**

Add this constant beside the other path constants in `tests/test_aot_milestone6.py`:

```python
AARCH64_ASM_PATH = ROOT / "src/xcc/aarch64_asm.py"
```

Add this test to `AotMilestone6AdmissionTests`:

```python
    def test_admits_aarch64_backend_without_reflection_or_nonlocal_state(self) -> None:
        analysis = analyze_path(AARCH64_ASM_PATH)
        self.assertIn("_AArch64AsmGen._prepare_frame", analysis.types.functions)
        self.assertIn("_AArch64AsmGen._walk_ast_children", analysis.types.functions)
```

- [x] **Step 2: Replace reflection-style AST traversal**

In `src/xcc/aarch64_asm.py`, remove `fields` and `is_dataclass` from the dataclass import:

```python
from dataclasses import dataclass
```

Add explicit child traversal to `_AArch64AsmGen`:

```python
    def _walk_ast_children(self, node: object, walk: Callable[[object], None]) -> None:
        if isinstance(node, (str, int, float, bytes, type(None))):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, FunctionDef):
            walk(node.return_type)
            for param in node.params:
                walk(param.type_spec)
            if node.body is not None:
                walk(node.body)
            return
        if isinstance(node, CompoundStmt):
            for statement in node.statements:
                walk(statement)
            return
        if isinstance(node, BinaryExpr):
            walk(node.left)
            walk(node.right)
            return
        if isinstance(node, CallExpr):
            walk(node.callee)
            for arg in node.args:
                walk(arg)
            return
        if isinstance(node, StatementExpr):
            walk(node.body)
            return
```

Extend the helper in the implementation to cover every AST node shape imported by `aarch64_asm.py`: declarations, statements, initializer lists, type specs, expressions, GNU statement expressions, generic selections, label-address expressions, and indirect gotos. Do not fall back to `getattr`, `fields`, or `is_dataclass`.

- [x] **Step 3: Replace `nonlocal` layout/global state**

Add small state containers near the existing local dataclasses:

```python
@dataclass
class _FrameLayoutState:
    offset: int = 0


@dataclass
class _GlobalDataState:
    emitted_section: bool = False


@dataclass
class _GlobalRecordBitfieldState:
    offset: int = 0
    active_bit_base: int = 0
    active_bit_size: int = 0
    active_bit_used: int = 0
    active_bit_type: Type | None = None
    active_bit_value: int = 0
```

Use these objects in `_prepare_frame()`, `_emit_global_data()`, and `_emit_global_record_initializer()` so nested helpers mutate fields instead of rebinding outer-scope variables.

- [x] **Step 4: Test explicit traversal edge nodes**

Add this test to `tests/test_aarch64_asm.py`:

```python
    def test_ast_child_walker_covers_explicit_edge_nodes(self) -> None:
        gen = _AArch64AsmGen(compile_source("int f(void){return 0;}", filename="test.c"))
        seen: list[object] = []

        def collect(node: object) -> None:
            seen.append(node)

        low = IntLiteral("1")
        high = IntLiteral("2")
        gen._walk_ast_children(DesignatorRange(low, high), collect)

        enum_value = IntLiteral("3")
        atomic_target = TypeSpec("int")
        typeof_expr = Identifier("typed")
        gen._walk_ast_children(
            TypeSpec(
                "enum",
                enum_members=(("EMPTY", None), ("VALUE", enum_value)),
                atomic_target=atomic_target,
                typeof_expr=typeof_expr,
            ),
            collect,
        )

        body = CompoundStmt([ReturnStmt(IntLiteral("0"))])
        gen._walk_ast_children(StatementExpr(body), collect)
        gen._walk_ast_children(IndirectGotoStmt(Identifier("label_ptr")), collect)

        for expected in (low, high, enum_value, atomic_target, typeof_expr, body):
            with self.subTest(expected=expected):
                self.assertIn(expected, seen)
```

Import the AST node classes used by the test from `xcc.ast`.

- [x] **Step 5: Verify AArch64 admission and backend tests**

Run:

```bash
uv run python -m unittest tests.test_aot_milestone6 tests.test_aarch64_asm -v
```

Expected: all tests pass.

- [x] **Step 6: Commit AArch64 admission cleanup**

Run:

```bash
git add src/xcc/aarch64_asm.py tests/test_aarch64_asm.py tests/test_aot_milestone6.py CHANGELOG.md
git commit -m "feat: admit AOT AArch64 assembler"
```

## Task 3: Add Bootstrap Source Graph Reporting

**Files:**

- Create: `src/xcc/aot/bootstrap.py`
- Modify: `src/xcc/aot/__init__.py`
- Create: `tests/test_aot_bootstrap.py`

- [x] **Step 1: Write failing bootstrap graph tests**

Create `tests/test_aot_bootstrap.py`:

```python
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, collect_bootstrap_sources, summarize_bootstrap_admission


ROOT = Path(__file__).resolve().parents[1]


class AotBootstrapGraphTests(unittest.TestCase):
    def test_collects_all_src_xcc_modules_in_deterministic_order(self) -> None:
        modules = collect_bootstrap_sources(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py")))
        self.assertEqual(len(modules), expected_count)
        self.assertEqual(modules[0].name, "xcc.__init__")
        self.assertIn("xcc.aot.bootstrap", {module.name for module in modules})
        self.assertEqual(modules[-1].name, "xcc.x86_64_asm")

    def test_rejects_non_repository_root(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_bootstrap_sources(ROOT / "tests")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0001")

    def test_summarizes_bootstrap_admission(self) -> None:
        report = summarize_bootstrap_admission(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py")))
        self.assertEqual(report.total, expected_count)
        self.assertEqual(report.failed, ())
```

- [x] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapGraphTests -v
```

Expected: import failure for `collect_bootstrap_sources`.

- [x] **Step 3: Implement bootstrap graph collection**

Create `src/xcc/aot/bootstrap.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.analysis import analyze_path
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.slice import AotSliceInput


@dataclass(frozen=True)
class AotBootstrapAdmissionReport:
    total: int
    failed: tuple[str, ...]


def collect_bootstrap_sources(root: Path) -> tuple[AotSliceInput, ...]:
    src_xcc = root / "src" / "xcc"
    if not src_xcc.is_dir():
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-BOOTSTRAP-0001",
                    f"Bootstrap root does not contain src/xcc: {root}",
                    filename=str(root),
                ),
            )
        )
    src_xcc = src_xcc.resolve()
    modules: list[AotSliceInput] = []
    for path in sorted(src_xcc.rglob("*.py")):
        resolved = path.resolve()
        relative = resolved.relative_to(src_xcc)
        modules.append(AotSliceInput(_bootstrap_module_name(relative), resolved))
    modules.sort(key=_bootstrap_input_name)
    return tuple(modules)


def summarize_bootstrap_admission(root: Path) -> AotBootstrapAdmissionReport:
    failures: list[str] = []
    modules = collect_bootstrap_sources(root)
    for module in modules:
        try:
            analyze_path(module.path)
        except AotError as exc:
            failures.append(f"{module.name}: {exc}")
    return AotBootstrapAdmissionReport(len(modules), tuple(failures))


def _bootstrap_module_name(relative: Path) -> str:
    return "xcc." + ".".join(relative.with_suffix("").parts)


def _bootstrap_input_name(module: AotSliceInput) -> str:
    return module.name
```

Export `AotBootstrapAdmissionReport`, `collect_bootstrap_sources`, and `summarize_bootstrap_admission` from `src/xcc/aot/__init__.py`.

- [x] **Step 4: Run bootstrap graph tests**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapGraphTests -v
```

Expected: all tests pass.

- [x] **Step 5: Commit bootstrap graph reporting**

Run:

```bash
git add src/xcc/aot/__init__.py src/xcc/aot/bootstrap.py tests/test_aot_bootstrap.py
git commit -m "feat: add AOT bootstrap source graph"
```

## Task 4: Plan and Lower the Native `xcc` Entry

**Files:**

- Modify: `src/xcc/aot/bootstrap.py`
- Modify: `src/xcc/aot/__init__.py`
- Modify: `tests/test_aot_bootstrap.py`

- [x] **Step 1: Add failing entry-plan tests**

Append to `tests/test_aot_bootstrap.py`:

```python
from xcc.aot import plan_bootstrap_entry


class AotBootstrapEntryTests(unittest.TestCase):
    def test_plans_cc_driver_main_as_bootstrap_entry(self) -> None:
        plan = plan_bootstrap_entry(ROOT)
        self.assertEqual(plan.entry_symbol, "xcc.cc_driver.main")
        self.assertIn("xcc.cc_driver", plan.modules)
        self.assertIn("xcc.frontend", plan.modules)
        self.assertIn("xcc.parser.__init__", plan.modules)
        self.assertIn("xcc.sema.__init__", plan.modules)

    def test_entry_plan_contains_target_backends(self) -> None:
        plan = plan_bootstrap_entry(ROOT)
        self.assertIn("xcc.x86_64_asm", plan.modules)
        self.assertIn("xcc.aarch64_asm", plan.modules)
        self.assertIn("xcc.llvm_api", plan.modules)
```

- [x] **Step 2: Run entry-plan tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapEntryTests tests.test_aot_bootstrap.AotBootstrapLoweringTests -v
```

Expected: import failure for `lower_bootstrap_entry_smoke`.

- [x] **Step 3: Implement bootstrap entry planning**

Add to `src/xcc/aot/bootstrap.py`:

```python
@dataclass(frozen=True)
class AotBootstrapEntryPlan:
    entry_symbol: str
    modules: tuple[str, ...]


_BOOTSTRAP_REQUIRED_MODULES = (
    "xcc.__init__",
    "xcc.aarch64_asm",
    "xcc.ast",
    "xcc.cc_driver",
    "xcc.codegen",
    "xcc.diag",
    "xcc.frontend",
    "xcc.lexer",
    "xcc.llvm_api",
    "xcc.options",
    "xcc.parser.__init__",
    "xcc.preprocessor.__init__",
    "xcc.sema.__init__",
    "xcc.types",
    "xcc.x86_64_asm",
)


def plan_bootstrap_entry(root: Path) -> AotBootstrapEntryPlan:
    available = {module.name for module in collect_bootstrap_sources(root)}
    missing = tuple(name for name in _BOOTSTRAP_REQUIRED_MODULES if name not in available)
    if missing:
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-BOOTSTRAP-0002",
                    f"Missing bootstrap modules: {', '.join(missing)}",
                    filename=str(root),
                ),
            )
        )
    return AotBootstrapEntryPlan("xcc.cc_driver.main", _BOOTSTRAP_REQUIRED_MODULES)
```

Export `AotBootstrapEntryPlan` and `plan_bootstrap_entry` from `src/xcc/aot/__init__.py`.

- [x] **Step 4: Run entry-plan tests**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapEntryTests -v
```

Expected: all tests pass.

- [x] **Step 5: Lower one bootstrap-reachable wrapper**

Reuse the existing core entry lowering helpers to lower a wrapper that calls a bootstrap-reachable leaf, in this slice `xcc.options.FrontendOptions.__post_init__`. Add a test that proves the wrapper is lowered by name rather than hard-coded output:

```python
from xcc.aot import lower_bootstrap_entry_smoke


class AotBootstrapLoweringTests(unittest.TestCase):
    def test_lowers_bootstrap_entry_smoke_wrapper(self) -> None:
        module = lower_bootstrap_entry_smoke(ROOT)
        functions = {function.name: function for function in module.functions}
        self.assertIn("aot_bootstrap_smoke_main", functions)
        self.assertIn("xcc.options.FrontendOptions.__post_init__", functions)
        self.assertIn("FrontendOptions", {record.name for record in module.records})
        self.assertIn(
            "target='xcc.options.FrontendOptions.__post_init__'",
            repr(functions["aot_bootstrap_smoke_main"].body),
        )
```

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapLoweringTests -v
```

Expected: the smoke wrapper lowers to AOT IR.

- [x] **Step 6: Commit bootstrap entry planning**

Run:

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-27-aot-python-milestone-6.md src/xcc/aot/__init__.py src/xcc/aot/bootstrap.py tests/test_aot_bootstrap.py
git commit -m "feat: plan AOT bootstrap entry"
```

## Task 5: Build the Native Bootstrap Executable

**Files:**

- Modify: `src/xcc/aot/bootstrap.py`
- Modify: `src/xcc/aot/native.py`
- Modify: `src/xcc/aot/llvm_text.py`
- Modify: `src/xcc/aot/core_runtime.py`
- Modify: `tests/test_aot_bootstrap.py`

- [x] **Step 1: Add mocked native build tests**

Append to `tests/test_aot_bootstrap.py`:

```python
from unittest.mock import patch

from xcc.aot import build_native_bootstrap


class AotBootstrapNativeBuildTests(unittest.TestCase):
    def test_build_native_bootstrap_invokes_llc_and_linker(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run(command: list[str], *args: object, **kwargs: object) -> object:
            commands.append(tuple(command))

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch("subprocess.run", fake_run):
            output = build_native_bootstrap(ROOT, ROOT / "build/aot/xcc")

        self.assertEqual(output, ROOT / "build/aot/xcc")
        self.assertTrue(any("llc" in command[0] for command in commands))
        self.assertTrue(any(command[0] == "cc" for command in commands))
```

- [x] **Step 2: Run mocked native build tests and verify they fail**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapNativeBuildTests -v
```

Expected: import failure for `build_native_bootstrap`.

- [x] **Step 3: Implement native bootstrap build orchestration**

Add `build_native_bootstrap(root: Path, output: Path) -> Path` to `src/xcc/aot/bootstrap.py`. It must:

- call `plan_bootstrap_entry(root)`;
- lower the bootstrap entry module graph;
- emit textual LLVM IR through `src/xcc/aot/llvm_text.py`;
- write temporary `.ll` and `.o` files under `output.parent`;
- invoke the configured `llc` path through the existing native helper;
- invoke the host C linker only to link the already generated native object and runtime support;
- return `output` on success;
- raise `AotError` with `XCC-AOT-BOOTSTRAP-0003` when a command fails.

- [x] **Step 4: Run mocked native build tests**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapNativeBuildTests -v
```

Expected: mocked command planning tests pass.

- [x] **Step 5: Add an optional real toolchain smoke**

Add a test guarded by `llc` availability:

```python
    def test_real_native_bootstrap_smoke_when_llc_exists(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        output = build_native_bootstrap(ROOT, ROOT / "build/aot/xcc-smoke")
        self.assertTrue(output.exists())
```

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapNativeBuildTests -v
```

Expected: mocked test passes and real smoke either passes or is skipped when the configured `llc` is unavailable.

- [x] **Step 6: Commit native bootstrap build helper**

Run:

```bash
git add src/xcc/aot/bootstrap.py src/xcc/aot/native.py src/xcc/aot/llvm_text.py src/xcc/aot/core_runtime.py tests/test_aot_bootstrap.py
git commit -m "feat: build native AOT bootstrap executable"
```

## Task 6: Validate Self-Hosting Inputs

**Files:**

- Modify: `src/xcc/aot/bootstrap.py`
- Modify: `tests/test_aot_bootstrap.py`
- Modify: `CHANGELOG.md`

- [x] **Step 1: Add self-host harness tests**

Append to `tests/test_aot_bootstrap.py`:

```python
import subprocess
from unittest.mock import patch

from xcc.aot import AotBootstrapRunResult, run_bootstrap_self_host_smoke


class AotBootstrapSelfHostHarnessTests(unittest.TestCase):
    def test_self_host_harness_invokes_generated_executable_with_c_input(self) -> None:
        def fake_build(root, output, *, llc=None, cc="cc"):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("#!/bin/sh\n", encoding="utf-8")
            return output

        def fake_run(command, **kwargs):
            output_path = Path(command[4])
            output_path.write_bytes(b"object")
            return subprocess.CompletedProcess(command, 0, stdout="compiled\n", stderr="")

        with (
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            result = run_bootstrap_self_host_smoke(ROOT, llc="/tool/llc", cc="clang")

        self.assertIsInstance(result, AotBootstrapRunResult)
        self.assertEqual(result.returncode, 0)
        self.assertIn("compiled", result.stdout)
```

- [x] **Step 2: Run self-host harness tests and verify they fail before implementation**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapSelfHostHarnessTests -v
```

Expected before implementation: import failure for `AotBootstrapRunResult`.

- [x] **Step 3: Implement the self-host smoke helper**

Add to `src/xcc/aot/bootstrap.py`:

```python
@dataclass(frozen=True)
class AotBootstrapRunResult:
    returncode: int
    stdout: str
    stderr: str
```

Implement `run_bootstrap_self_host_smoke(root: Path) -> AotBootstrapRunResult` so it:

- builds the native bootstrap executable under `build/aot/xcc`;
- invokes the generated executable, not `python -m xcc`;
- compiles a stable project-owned C smoke input that already exists in the test suite or writes one under a temporary directory;
- returns stdout, stderr, and status;
- raises `AotError` only for harness setup failures, not for normal compiler diagnostics.
- deletes stale output objects before invoking the generated executable and
  returns a non-zero result if the executable reports success without producing
  the expected object.

- [x] **Step 4: Run current self-host harness**

Run:

```bash
uv run python -m unittest tests.test_aot_bootstrap.AotBootstrapSelfHostHarnessTests -v
uv run python - <<'PY'
from pathlib import Path
from xcc.aot import run_bootstrap_self_host_smoke
result = run_bootstrap_self_host_smoke(Path('.').resolve())
print('returncode=', result.returncode)
print('stdout=', repr(result.stdout))
print('stderr=', repr(result.stderr))
PY
```

Expected current result: the harness invokes the generated native executable and
reports `missing output object`. This is not final self-host success; it is the
correct current signal until native lowering emits a real compiler entry that
can produce an object file.

- [x] **Step 4b: Validate native argv bridge self-host smoke success**

Run after the generated native executable has a real argv-aware native entry:

```bash
uv run python - <<'PY'
from pathlib import Path
from xcc.aot import run_bootstrap_self_host_smoke
result = run_bootstrap_self_host_smoke(Path('.').resolve())
assert result.returncode == 0, result
assert result.stderr == "", result
assert Path('build/aot/self-host-smoke.o').exists()
PY
```

Verified current result: the generated native `xcc` exposes `main(argc, argv)`
and runs a compiled `execvp("cc", argv)` delegate, so the self-host smoke returns
0 and produces `build/aot/self-host-smoke.o` without entering the CPython runtime.
This is not final project-owned compiler behavior; it is a transition bridge for
argv handling and native process execution.

- [x] **Step 4c: Validate project-owned smoke compiler bridge**

Run after the bootstrap entry no longer delegates to host `cc` and instead uses
a project-owned AOT smoke compiler leaf for the smoke input:

```bash
uv run python - <<'PY'
from pathlib import Path
from xcc.aot import run_bootstrap_self_host_smoke
result = run_bootstrap_self_host_smoke(Path('.').resolve())
assert result.returncode == 0, result
assert result.stderr == "", result
assert Path('build/aot/self-host-smoke.o').exists()
assert Path('build/aot/self-host-smoke.o.ll').exists()
PY
```

Verified current result: the generated native `xcc` validates the exact
project-owned smoke source, writes minimal LLVM IR for it, invokes
`/opt/homebrew/opt/llvm/bin/llc`, returns 0, and produces
`build/aot/self-host-smoke.o` without CPython or host `cc`.

- [ ] **Step 4d: Validate project-owned frontend/backend self-host smoke success**

Run after the bootstrap entry no longer uses the fixed smoke compiler leaf and
instead lowers the project-owned frontend/backend path for the smoke input:

```bash
uv run python - <<'PY'
from pathlib import Path
from xcc.aot import run_bootstrap_self_host_smoke
result = run_bootstrap_self_host_smoke(Path('.').resolve())
assert result.returncode == 0, result
assert result.stderr == "", result
assert Path('build/aot/self-host-smoke.o').exists()
PY
```

Expected final result: the generated native `xcc` compiles the smoke input
through lowered project-owned frontend/backend code, returns 0, and produces
`build/aot/self-host-smoke.o`.

Current progress toward this step: `_aot_compile_smoke_source_to_object` is now
real CPython-valid project code that delegates fixed command validation to
lowered project helper `xcc.cc_driver._aot_is_smoke_compile_command()`, fixed
smoke-source validation to lowered project helper
`xcc.cc_driver._aot_is_smoke_source()`, `.ll` path construction to lowered
project helper `xcc.cc_driver._aot_smoke_llvm_path()`, fixed `llc` argv
construction to lowered project helper `xcc.cc_driver._aot_smoke_llc_argv()`,
source-file reading to project helper `xcc.cc_driver._aot_read_text_file()`,
LLVM file writing to project helper `xcc.cc_driver._aot_write_text_file()`, and
`llc` process execution to project helper `xcc.cc_driver._aot_exec_argv()`. The
fixed smoke LLVM text has also moved into lowered project helper
`xcc.cc_driver._aot_smoke_llvm_ir()`. The smoke compiler body now delegates the
source text to LLVM IR step to project helper
`xcc.cc_driver._aot_compile_source_to_llvm_ir()` instead of directly calling
the fixed smoke source validator and fixed smoke IR helper. Under CPython, that
new helper runs the real frontend and LLVM backend for the provided source text;
under native AOT it is still a temporary smoke-only leaf that calls the existing
validator and fixed smoke IR helper. That boundary is now split into an
exception-handling wrapper and a lowerable unchecked helper,
`xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked()`, whose ordinary body
now calls a lowerable frontend success helper and then `generate_llvm_ir()`.
The frontend success path is split into
`xcc.frontend._aot_compile_source_unchecked()`, whose ordinary body exposes
`normalize_options()`, `preprocess_source()`, `lex()`, `parse()`, `analyze()`,
and `FrontendResult(...)` without changing `compile_source()`'s diagnostic
wrappers. The AOT lower/slice path now admits imported project call names,
rewrites `from xcc... import ...` calls to fully qualified slice targets, and
retains keyword argument values in lowered calls. AOT lowering now maps existing
`dict[...]`, `set[...]`, `frozenset[...]`, `Iterable[...]`, and `Sequence[...]`
annotations to the current tuple-backed opaque runtime shape, allowing the
cross-module frontend success-path slice to get past `SemaUnit`'s container
fields. AOT IR/lower/slice/LLVM now supports ordinary `while` loops with
loop-carried local phi values and integer ordering comparisons, so the frontend
success-path slice advances past `xcc.lexer.lex()`'s loop shape. AOT lowering
and LLVM emission now support enum member constants such as `TokenKind.EOF`
with stable per-module constant pointers, the type binder infers ordinary
instance fields assigned in `__init__` for method field reads such as
`self._line`, and loop control now lowers/emits `break` and `continue` for
`while` and tuple-backed `for` loops. AOT lowering, LLVM emission, and runtime
support now handle existing `str.startswith(prefix[, start])` calls, and the
lowerer handles integer `+=`/`-=`/`*=` assignments to local names and instance
fields. AOT lowering now handles existing `NoReturn` annotations, no-argument
string predicates (`isalpha`, `isdigit`, `isalnum`, `isspace`),
signature-aware project method return/argument types, target-aware assignment
value lowering, literal assignment inference, `int(text, base)` parsing, and
chained comparisons. LLVM emission now lowers the string predicates and integer
parse calls through runtime helpers. Lexer number classification now uses
ordinary scanner helpers instead of runtime regex `fullmatch`, and block-comment
scanning no longer uses `while ... else`. The frontend success-path slice now
lowers through lexer number classification and comment skipping. Codegen's LLVM
module printing is now isolated behind the typed
`_llvm_print_module_to_string(module: int) -> str` helper, and that helper is an
explicit AOT native LLVM-C leaf. Tuple-backed container annotations now retain
homogeneous element types, allowing `for` targets over fields such as
`TranslationUnit.functions` to bind as project records. The broader
source-to-LLVM unchecked slice now advances past `_LLVMGen.generate()`; the next
observed blocker is the existing `self._sema.functions.get(...)` dictionary
lookup/optional `FunctionSymbol` boundary in `codegen.py`. AOT lowering now
handles existing `dict[str, T].get(key)` calls over the tuple-backed container
shape, applies simple optional-record narrowing after `if value is None:
return` guards, and lowers empty `{}` literals as empty tuple-backed containers
when the expected type is a supported dict shape. The broader source-to-LLVM
unchecked slice now advances past `self._sema.functions.get(...)`; the next
observed blocker is the existing `enumerate(real_params)` loop in `codegen.py`.
AOT lowering now handles existing `enumerate(iterable)` loops and subscript
assignment statements such as `param_ts[i] = lt`; LLVM text emission treats
enumerate loops as ordinary tuple-backed loops with the loop index bound to the
first target and emits pointer stores for lowered subscript assignment. The
broader source-to-LLVM unchecked slice now advances past the
`enumerate(real_params)` loop; the next observed blocker is the existing
`c.FunctionType(...)` LLVM-C receiver call in `codegen.py`.
AOT lowering now handles the existing `llvm()` API handle pattern and
`c.FunctionType(...)` LLVM-C receiver call shape, and LLVM text emission lowers
that call directly to `LLVMFunctionType`. Existing `str.encode()` calls lower
as C-string identity values, and bytes literals such as `b"entry"` lower as AOT
string constants for LLVM-C names. The broader source-to-LLVM unchecked slice
now advances past `c.FunctionType(...)`, `func.name.encode()`, and
`c.AppendBasicBlock(fn, b"entry")`; the next observed blocker is `symbol.type_`
after `isinstance(symbol, VarSymbol)` in `codegen.py`.
AOT lowering now handles `isinstance(...)` branch narrowing over union/base
record types, optional attribute guards (`is not None` and truthy checks),
class-level integer constants, Python float literals, negative indexes, unary
integer `+`, `-`, and `~`, `int(bool)` coercion, tuple-backed `pop()`, and
`pass` statements. Core slice lowering now also injects cross-module method
signatures. The broader source-to-LLVM unchecked slice now advances past
`symbol.type_`, `self._locals[-1]`, `LLVMTypeKind.POINTER`,
`c.ConstReal(..., 0.0)`, `stmt.statements`, `self._locals.pop()`, `pass`,
`_eval_case_val` unary operators, and optional `self._func_sym` /
`self._sema.file_scope` guards; the next observed blocker is `left // right` in
`codegen.py`.
AOT lowering now handles the existing integer floor-division/modulo and
bitwise operator shapes, normal-path `try` handlers, integer `min`/`max`,
`range`, `chr`, `float`, `float.fromhex`, `str.find`, `str.split`,
`str.endswith`, `str.ljust`, `str.rstrip`, `int.to_bytes`, `bytes`, `id`,
`zip(..., strict=True)`, tuple-backed `dict.items()`, empty container
constructors, tuple identity conversion, tuple-backed `add`/`append`, expected
types for list/generator comprehensions, optional tuple-backed top-level
unions, attribute-aware `isinstance` narrowing, `if` expression `is not None`
narrowing, exiting `not isinstance` narrowing, and common field access over
record unions. Codegen has also been reshaped away from several bootstrap-hostile
source patterns while staying CPython-valid: small local dict dispatch,
generator `max`, nested callback key functions, starred list literals, untyped
optional symbol lookups, atomic opcode dictionaries, compound operator
dictionaries, nested helper functions, subscript-target mutating calls,
non-empty dict literals, bytearray-backed constant assembly, dead `_term`
writes, and Optional if-expression field access. AOT lowering now supports
tuple-of-class `isinstance` narrowing for common record-field access, so codegen
can keep the ordinary CPython form where ruff expects it.
The broader source-to-LLVM unchecked slice rooted at
`xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked` now lowers to AOT IR
successfully, currently covering 237 functions and 62 records. LLVM text
emission and runtime coverage now exists for the newly discovered
`str.ljust`, `str.rstrip`, `bytes`, `int.to_bytes`, and `id` intrinsics, with
native smoke coverage for observable string/byte/id paths. The remaining Step
4d work is the broader lowered codegen emission/execution path plus
length-aware bytes semantics beyond the current C-string-compatible buffer
shape.
The generated
`main(argc, argv)` now converts the platform C `argv` array into the AOT tuple
ABI with
`__xcc_aot_c_argv_to_tuple()`, the native smoke compiler leaf reads its
Python-level `argv` through `__xcc_aot_tuple_get()`, source reading goes through
a generic `__xcc_aot_read_text_file()` runtime shim, LLVM file writing goes
through a generic `__xcc_aot_write_text_file()` runtime shim, and process
execution goes through the generic AOT tuple-to-`execvp` runtime shim behind the
project helper. Ordinary lowered Python tuple indexing now emits
`__xcc_aot_tuple_get()`, so `argv[1]`, `argv[2]`, and related smoke compiler
body expressions can move out of the native-special shell. Ordinary lowered
Python tuple length checks now emit `__xcc_aot_tuple_len()`, so `len(argv) != 5`
can also move out of the native-special shell without falling back to a dynamic
`@len` call. The Python body of `_aot_compile_smoke_source_to_object()` no
longer builds a `Path` object or calls `str()` to bridge back to string paths;
its path values, read text, emitted LLVM text, and `llc` argv are now annotated
locals, and the body lowers and emits through the generic AOT path in isolation.
The bootstrap slice now selects that generic lowered body instead of emitting a
native-special smoke compiler shell, so the generated native `xcc` reaches the
smoke compiler through ordinary lowered tuple length/indexing, branching, and
project helper calls. The remaining gap for Step 4d is lowering the general
project-owned frontend/backend implementation behind the unchecked frontend and
source-to-LLVM helpers, then replacing the smoke-only native leaf
specialization at `_aot_compile_source_to_llvm_ir()`.

- [ ] **Step 5: Run the CPython build target smoke with native `xcc`**

Run this only after Step 4d passes:

```bash
tmpdir="$(mktemp -d /private/tmp/xcc-cpython-aot.XXXXXX)"
cd "$tmpdir"
git clone --depth 1 https://github.com/python/cpython.git cpython
cd cpython
CC="/Users/tcztzy/GitHub/xcc/build/aot/xcc" ./configure
make -j8
```

Expected: `configure` and `make` complete with `CC` pointing at the generated native `xcc`. Record optional dependency skips separately from compiler failures.

- [ ] **Step 6: Record final Milestone 6 status**

Add to `CHANGELOG.md` only after Step 4d passes:

```markdown
- Completed Milestone 6 native bootstrap smoke: the generated native `xcc`
  executable is built from the accepted Python source without the CPython
  runtime and compiles the project-owned self-host smoke input successfully.
```

Add the CPython build result only after Step 5 completes:

```markdown
- Validated the native `xcc` as `CC` for a CPython `configure && make` run.
```

- [ ] **Step 7: Commit self-host validation**

Run:

```bash
git add src/xcc/aot/bootstrap.py tests/test_aot_bootstrap.py CHANGELOG.md
git commit -m "test: validate AOT bootstrap self-host smoke"
```

## Final Verification

Run these commands before handoff after any Milestone 6 code slice:

```bash
uv run python -m unittest tests.test_aot_milestone6 -v
uv run tox -e lint
uv run tox -e type
uv run tox -e py311
git diff --check
```

For final bootstrap completion, also run:

```bash
uv run python -m unittest tests.test_aot_bootstrap -v
```

If the CPython compiler target is being claimed, also run:

```bash
CC="/Users/tcztzy/GitHub/xcc/build/aot/xcc" ./configure
make -j8
```

from a clean CPython checkout, and record the exact checkout path, command output summary, and result in `CHANGELOG.md`.
