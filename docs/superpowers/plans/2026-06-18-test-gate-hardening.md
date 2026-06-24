# Test Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make XCC's default verification path parallel, coverage-aware, mypyc-aware, and explicit about full CPython build validation.

**Architecture:** Add a stdlib-only test runner that discovers unittest modules, runs them in subprocess shards, and merges coverage data. Route tox, CI, and pre-commit through the same gates, add a first-tier mypyc tox path, and add a CPython clean-build validation script so single-file frontend benchmarks cannot be mistaken for real-project evidence.

**Tech Stack:** Python 3.11 standard library runtime, unittest, coverage.py dev tooling, tox-uv, pre-commit, GitHub Actions.

---

### Task 1: Parallel Test Runner

**Files:**
- Create: `scripts/run_tests.py`
- Create: `tests/test_run_tests.py`
- Modify: `pyproject.toml`

- [x] **Step 1: Write failing tests**

```python
def test_discover_test_modules_returns_importable_sorted_names(self) -> None:
    runner = _load_runner_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tests = root / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "test_b.py").write_text("", encoding="utf-8")
        (tests / "test_a.py").write_text("", encoding="utf-8")

        modules = runner.discover_test_modules(root=root, start_dir=tests)

    self.assertEqual(modules, ["tests.test_a", "tests.test_b"])
```

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m unittest tests.test_run_tests -v`
Expected: FAIL because `scripts/run_tests.py` does not exist.

- [x] **Step 3: Implement `scripts/run_tests.py`**

Create a stdlib-only runner that:
- discovers `test*.py` modules under `tests/`
- accepts `--jobs auto|N`, `--coverage`, `--fail-under`, and `--pythonpath`
- runs each module through `python -m unittest -v <module>` in subprocesses
- uses `python -m coverage run --parallel-mode -m unittest -v <module>` when coverage is enabled
- runs `coverage erase`, `coverage combine`, and `coverage report` around parallel coverage runs

- [x] **Step 4: Route tox test envs through the runner**

Change `[tool.tox.env_run_base].commands` to:

```toml
commands = [["python", "scripts/run_tests.py", "--coverage"]]
```

- [x] **Step 5: Verify focused tests pass**

Run: `uv run python -m unittest tests.test_run_tests -v`
Expected: PASS.

### Task 2: Gate Configuration

**Files:**
- Modify: `.pre-commit-config.yaml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_run_tests.py`
- Modify: `README.md`

- [x] **Step 1: Write failing config tests**

Add tests that assert:
- tox runs `scripts/run_tests.py --coverage`
- pre-commit has local test, lint, and type hooks
- CI invokes tox test, lint, and type gates instead of a separate unittest command

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m unittest tests.test_run_tests -v`
Expected: FAIL on missing config contracts.

- [x] **Step 3: Update pre-commit and CI**

Add local always-run hooks:

```yaml
- id: xcc-test-gate
  entry: uv run tox -e py311
- id: xcc-lint-gate
  entry: uv run tox -e lint
- id: xcc-type-gate
  entry: uv run tox -e type
```

Change CI to use the tox test gate:

```yaml
- name: Run test gate
  run: uv run tox -e py311
```

- [x] **Step 4: Verify focused tests pass**

Run: `uv run python -m unittest tests.test_run_tests -v`
Expected: PASS.

### Task 3: First-Tier mypyc Gate

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_benchmark.py`
- Modify: `README.md`

- [x] **Step 1: Write failing tox test**

Extend `BenchmarkToxConfigTests` to assert a `mypyc` tox env builds `scripts/mypycize_xcc.py --clean --force` and runs `scripts/run_tests.py --pythonpath build/mypyc/lib`.

- [x] **Step 2: Verify test fails**

Run: `uv run python -m unittest tests.test_benchmark.BenchmarkToxConfigTests -v`
Expected: FAIL because no first-tier `mypyc` env exists.

- [x] **Step 3: Add the tox env**

Add `[tool.tox.env.mypyc]` with dev dependencies, CPython 3.11, mypyc build, and compiled-import-tree tests.

- [x] **Step 4: Verify focused test passes**

Run: `uv run python -m unittest tests.test_benchmark.BenchmarkToxConfigTests -v`
Expected: PASS.

### Task 4: Full CPython Build Validation Entry

**Files:**
- Create: `scripts/validate_cpython_build.py`
- Create: `tests/test_cpython_build.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [x] **Step 1: Write failing tests**

Add tests that assert the script constructs a clean out-of-tree `configure` and `make` flow using `CC=xcc`, `XCC_LLC=/opt/homebrew/opt/llvm/bin/llc` when present, caller-provided `--jobs`, and no single source-file substitution.

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m unittest tests.test_cpython_build -v`
Expected: FAIL because the script does not exist.

- [x] **Step 3: Implement the script**

Create a stdlib-only script with `--cpython`, `--build-dir`, `--cc`, `--jobs`, `--configure-arg`, `--make-arg`, `--skip-configure`, `--timeout`, and `--keep-going`.

- [x] **Step 4: Add tox entry**

Add `[tool.tox.env.cpython-build]` that runs:

```toml
commands = [["python", "scripts/validate_cpython_build.py", "--cpython", "{posargs:../cpython}"]]
```

- [x] **Step 5: Verify focused tests pass**

Run: `uv run python -m unittest tests.test_cpython_build -v`
Expected: PASS.

### Task 5: Verification and Ledger

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `LESSONS.md`

- [x] **Step 1: Run focused tests**

Run:

```bash
uv run python -m unittest tests.test_run_tests tests.test_benchmark tests.test_cpython_build -v
```

- [x] **Step 2: Run parallel test gate**

Run:

```bash
uv run python scripts/run_tests.py --coverage --jobs auto
```

- [x] **Step 3: Run required handoff gates**

Run:

```bash
uv run tox -e lint
uv run tox -e type
```

- [x] **Step 4: Update ledgers**

Add one `CHANGELOG.md` bullet for the hardened gates and one `LESSONS.md` bullet that says full CPython build validation must remain a separate real-project gate from frontend file benchmarks.

### Verification Snapshot

- `uv run python -m unittest tests.test_run_tests -v`: passed after the
  coverage contract was tightened to 86.2%.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_internal_helper_accepts_function_pointer_parameter
  tests.test_evm.EvmTargetTests.test_void_function_pointer_call_returns_to_dispatch_join
  tests.test_evm.EvmTargetTests.test_for_expression_init_and_void_post_execute_correctly
  tests.test_evm.EvmTargetTests.test_static_locals_inside_expression_trees_are_collected_before_initcode
  -v`: passed.
- `uv run python scripts/run_tests.py --coverage --fail-under 0`: passed with
  per-run isolated `COVERAGE_FILE` data, 17 modules across 8 workers, and
  coverage reporting 86.20698931963089% total, 2859 missing lines. The
  `sema/initializers.py` module reports 100%; the remaining below-100% files
  are `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run tox -e mypyc,lint,type`: passed; the mypyc env rebuilt
  `build/mypyc/lib` and ran the full test suite through the compiled import
  tree.
- `uv run pre-commit run --all-files`: passed, including local test, lint, and
  type gates.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  86.2% coverage ratchet update on the isolated clean CPython worktree with
  `configure && make -j8`, 116 modules checked, 0 failed imports, and `_gdbm`
  missing only from local dependencies.
- `uv run python -m unittest tests.test_codegen -v`: passed after adding the
  `_Alignof` regression tests.
- `uv run tox -e py311`: passed after the `_Alignof` fix; the coverage JSON
  reports 86.21775039681472% total coverage with 2857 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run tox -e mypyc,lint,type`: passed after the `_Alignof` fix; the mypyc
  env rebuilt `build/mypyc/lib` and ran the full test suite through the
  compiled import tree, then `ruff`, `ty`, and `mypy` passed.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  `_Alignof` fix on the isolated clean CPython worktree with `configure &&
  make -j8`, 116 modules checked, 37 built-in, 78 shared, `_gdbm` missing from
  local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_alignof_record_respects_explicit_member_alignment
  tests.test_x86_64_asm.X86_64AsmTests.test_sizeof_record_respects_explicit_member_alignment
  -v`: failed before the native backend `_Alignas` layout fix, then passed
  after AArch64 and x86_64 record layout paths switched to member storage
  alignment.
- `uv run python -m unittest tests.test_aarch64_asm -v`: passed after the
  native backend `_Alignas` layout fix with 155 tests.
- `uv run python -m unittest tests.test_x86_64_asm -v`: passed after the
  native backend `_Alignas` layout fix with 114 tests and 10 host-dependent
  native Linux execution tests skipped.
- `uv run tox -e py311`: passed after the native backend `_Alignas` layout
  fix; the coverage JSON reports 86.24593293715884% total coverage with 2850
  missing lines. The remaining below-100% files are still `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run tox -e mypyc,lint,type`: passed after the native backend `_Alignas`
  layout fix; the mypyc env rebuilt `build/mypyc/lib` and ran the full test
  suite through the compiled import tree, then `ruff`, `ty`, and `mypy`
  passed.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  native backend `_Alignas` layout fix on the isolated clean CPython worktree
  with `configure && make -j8`, 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing from local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_global_initializer_folds_integer_constant_operators
  tests.test_codegen.CodegenTests.test_global_initializer_folds_float_and_pointer_constant_casts
  -v`: passed after adding LLVM global constant-initializer coverage for
  integer operators, negative floating constants, pointer nulls, `inttoptr`,
  and `ptrtoint`.
- `uv run python -m unittest tests.test_codegen -v`: passed after the LLVM
  global constant-initializer coverage additions with 91 tests.
- `uv run tox -e py311`: passed after the LLVM global constant-initializer
  coverage additions; the coverage JSON reports 86.46373927774341% total
  coverage with 2805 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_switch_case_constant_operators_fold -v`:
  passed after adding LLVM switch case constant-expression coverage for
  division, remainder, shifts, bitwise operators, and conditional expressions.
- `uv run python -m unittest tests.test_codegen -v`: passed after the LLVM
  switch case constant-expression coverage addition with 92 tests.
- `uv run tox -e py311`: passed after the LLVM switch case
  constant-expression coverage addition; the coverage JSON reports
  86.51751862109764% total coverage with 2795 missing lines. The remaining
  below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`,
  and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_switch_case_logical_and_comparison_operators_fold
  -v`: failed before the LLVM `_eval_case_val` logical/comparison fix with the
  executable returning 1, then passed after case-label constant folding learned
  `==`, `!=`, `<`, `>`, `<=`, `>=`, `&&`, and `||`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_switch_case_constant_operators_fold
  tests.test_codegen.CodegenTests.test_switch_case_logical_and_comparison_operators_fold
  tests.test_codegen.CodegenTests.test_char_array_string_initializer_decodes_extended_escapes
  -v`: passed after expanding switch constant-expression and string escape
  coverage.
- `uv run python -m unittest tests.test_codegen -v`: passed after the LLVM
  switch logical/comparison fix and string escape coverage addition with 94
  tests.
- `uv run tox -e py311`: passed after the LLVM switch logical/comparison fix
  and string escape coverage addition; the coverage JSON reports
  86.60164960640499% total coverage with 2778 missing lines. The remaining
  below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`,
  and `evm.py`.
- `uv run python -m unittest tests.test_run_tests -v`: passed after tightening
  the coverage ratchet to 86.60%.
- `uv run tox -e py311`: passed with the 86.60% coverage ratchet enforced by
  the shared parallel coverage runner.
- `uv run tox -e mypyc,lint,type`: passed after the LLVM switch
  logical/comparison fix; the mypyc env rebuilt `build/mypyc/lib` and ran the
  full test suite through the compiled import tree, then `ruff`, `ty`, and
  `mypy` passed.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  LLVM switch logical/comparison fix on the isolated clean CPython worktree
  with `configure && make -j8`, 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing from local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_gnu_sync_compare_and_swap_builtins_run`:
  passed after adding GNU `__sync_val_compare_and_swap` and
  `__sync_bool_compare_and_swap` execution coverage.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_static_union_initializer_copies_nested_union_bytes_to_array_storage`:
  failed before the LLVM constant aggregate byte-extraction fix with the
  executable returning 1 because the global initializer emitted
  `zeroinitializer`, then passed after constant aggregate element lookup used
  `LLVMGetAggregateElement`.
- `uv run python -m unittest
  tests.test_llvm_api.LLVMApiTests.test_get_aggregate_element_reads_const_array_entries`:
  passed after adding the LLVM-C binding coverage.
- `uv run python -m unittest tests.test_codegen`: passed after the LLVM
  constant aggregate byte-extraction fix with 96 tests.
- `uv run python -m unittest tests.test_llvm_api`: passed after the LLVM-C
  aggregate-element binding with 5 tests.
- `uv run tox -e py311`: passed after the GNU sync CAS coverage and LLVM
  constant aggregate byte-extraction fix; the coverage JSON reports
  86.83284536248624% total coverage with 2719 missing lines. The remaining
  below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`,
  and `evm.py`.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  LLVM constant aggregate byte-extraction fix on the isolated clean CPython
  worktree with `configure && make -j8`, 116 modules checked, 37 built-in, 78
  shared, `_gdbm` missing from local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_gnu_atomic_pointer_form_builtins_run
  tests.test_codegen.CodegenTests.test_gnu_lock_free_memory_and_expect_builtins_run
  tests.test_codegen.CodegenTests.test_gnu_integer_bit_and_float_builtins_run
  -v`: the pointer-form atomic test passed immediately; the memory/floating
  builtin tests first exposed missing sema registration for
  `__builtin___memcpy_chk`, invalid LLVM memset fill typing, and invalid
  integer `fcmp` lowering for `__builtin_isinf(1)`, then passed after those
  fixes.
- `uv run python -m unittest tests.test_codegen -v`: passed after the builtin
  coverage and fixes with 99 tests.
- `uv run tox -e py311`: passed after the GNU builtin coverage additions; the
  coverage JSON reports 87.07398952598362% total coverage with 2657 missing
  lines. The remaining below-100% files are still `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run tox -e mypyc,lint,type`: passed after the GNU builtin fixes; the
  mypyc env rebuilt `build/mypyc/lib` and ran the full suite through the
  compiled import tree, then `ruff`, `ty`, and `mypy` passed.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  GNU builtin fixes on the isolated clean CPython worktree with
  `configure && make -j8`, 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing from local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_pointer_left_addition_prefix_updates_and_signed_bitfield_update
  tests.test_evm.EvmTargetTests.test_exported_function_shape_diagnostics -v`:
  initially exposed that EVM builtin arity diagnostics are sema-owned, so the
  unreachable backend arity test was removed; the remaining public EVM behavior
  and shape-diagnostic tests passed.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_grouped_storage_declarations_and_static_locals_use_slots
  tests.test_evm.EvmTargetTests.test_initialized_static_local_requires_initcode_generation
  tests.test_evm.EvmTargetTests.test_statement_expression_without_value_and_member_pointer_access
  tests.test_evm.EvmTargetTests.test_unavailable_external_call_reports_evm_diagnostic
  tests.test_evm.EvmTargetTests.test_unprototyped_function_pointer_call_reports_evm_diagnostic
  -v`: passed after adding EVM coverage for grouped declarations, initialized
  static locals, statement expressions without values, record pointer member
  access, missing external call bodies, and unprototyped function pointer calls.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_storage_initializer_diagnostics_are_reported_by_initcode
  tests.test_evm.EvmTargetTests.test_local_initializer_and_lvalue_diagnostics_are_reported_by_bytecode
  -v`: passed after adding reachable EVM initcode/local initializer diagnostics.
- `uv run python -m unittest tests.test_evm -v`: passed after the EVM coverage
  additions with 103 tests.
- `COVERAGE_FILE=/tmp/.coverage-xcc-evm uv run coverage run -m unittest
  tests.test_evm` plus `coverage json --fail-under=0`: passed and measured
  `evm.py` at 86.61275831087151% with 292 missing lines.
- `uv run tox -e py311`: passed after the EVM coverage additions; the coverage
  JSON reports 87.35061098428898% total coverage with 2601 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run tox -e mypyc,lint,type`: passed after the EVM coverage additions; the
  mypyc env rebuilt `build/mypyc/lib` and ran the full suite through the
  compiled import tree, then `ruff`, `ty`, and `mypy` passed.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  EVM coverage additions on the isolated clean CPython worktree with
  `configure && make -j8`, 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing from local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_gnu_atomic_variant_builtins_execute_inline
  -v`: passed after adding executable AArch64 coverage for generic GNU atomic
  load/store/exchange/compare-exchange, lock-free queries, fences, RMW
  variants, and `__sync_*compare_and_swap` lowering.
- `uv run python -m unittest tests.test_aarch64_asm -v`: passed after the
  AArch64 atomic coverage addition with 156 tests.
- `uv run tox -e py311`: passed after the AArch64 atomic coverage addition;
  the coverage JSON reports 87.65140324963072% total coverage with 2517
  missing lines, and `aarch64_asm.py` is up to 80.08540925266904% with 780
  missing lines. The remaining below-100% files are still `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed after the
  AArch64 atomic coverage addition on the isolated clean CPython worktree with
  `configure && make -j8`, 116 modules checked, 37 built-in, 78 shared,
  `_gdbm` missing from local dependencies, and 0 failed imports.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_local_wide_string_array_initializers_store_element_values
  -v`: first failed with invalid LLVM IR for `store [0 x i16] bitcast (ptr
  @.str to [0 x i16])`, then passed after string array initializer lowering
  used element-width-aware typed constants for `u""`, `U""`, and `L""`.
- `uv run python -m unittest tests.test_codegen -v`: passed after the wide
  string array initializer fix with 100 tests.
- `uv run tox -e py311`: passed after the wide string array initializer fix;
  the coverage JSON reports 87.65650553634146% total coverage with 2519
  missing lines, and `codegen.py` is up to 77.44319231479771% with 658 missing
  lines. The remaining below-100% files are still `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_local_enum_function_pointer_and_pointer_updates_execute
  tests.test_codegen.CodegenTests.test_mixed_float_pointer_comparisons_and_pointer_difference_execute
  -v`: passed after adding executable LLVM coverage for local enum lookup,
  function-pointer dereference, pointer updates, pointer difference scaling,
  mixed float comparisons, pointer/integer comparisons, and floating compound
  assignment.
- `uv run tox -e py311`: passed after the LLVM execution coverage additions;
  the coverage JSON reports 87.72889353601973% total coverage with 2501
  missing lines, and `codegen.py` is up to 77.94199150193977% with 640 missing
  lines. The remaining below-100% files are still `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_global_pointer_initializers_fold_compound_and_subobject_addresses
  tests.test_aarch64_asm.AArch64AsmTests.test_record_return_paths_execute_conditional_call_and_indirect_returns
  -v`: passed after adding executable Darwin AArch64 coverage for global
  pointer initializer forms and small/direct plus large/indirect record-return
  paths.
- `uv run tox -e py311`: passed after the AArch64 global initializer and
  record-return coverage additions; the coverage JSON reports
  87.81468672082362% total coverage with 2480 missing lines, and
  `aarch64_asm.py` is up to 80.54092526690391% with 759 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_variadic_definition_reads_aggregate_va_args
  -v`: first failed with `AArch64 target cannot address BuiltinVaArgExpr`,
  then passed after aggregate `__builtin_va_arg` lowering copied inline and
  by-reference Darwin varargs into local aggregate storage.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_global_pointer_initializers_fold_compound_and_subobject_addresses
  tests.test_aarch64_asm.AArch64AsmTests.test_record_return_paths_execute_conditional_call_and_indirect_returns
  tests.test_aarch64_asm.AArch64AsmTests.test_variadic_definition_reads_aggregate_va_args
  -v`: passed after the aggregate vararg fix.
- `uv run tox -e py311`: passed after the AArch64 aggregate vararg fix; the
  coverage JSON reports 87.8265762748198% total coverage with 2479 missing
  lines, and `aarch64_asm.py` is up to 80.62455642299503% with 758 missing
  lines. The remaining below-100% files are still `aarch64_asm.py`,
  `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_designated_local_initializers_use_word_storage_offsets
  tests.test_evm.EvmTargetTests.test_initcode_initializes_designated_storage_globals
  -v`: passed after folding nested local and storage initializer designator
  cases into the existing EVM bytecode/initcode coverage.
- `uv run tox -e py311`: passed after the nested EVM designator coverage; the
  coverage JSON reports 87.8372946756344% total coverage with 2477 missing
  lines, and `evm.py` is up to 86.7026055705301% with 290 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_terminal_return_stop_and_invalid_builtins_use_native_opcodes
  tests.test_evm.EvmTargetTests.test_backend_abi_and_function_pointer_diagnostics
  -v`: passed after adding explicit exported-void `return;` execution coverage
  and EVM source-level diagnostics for ABI/function-pointer shapes.
- `uv run tox -e py311`: passed after the EVM void-return and diagnostic
  coverage additions; the coverage JSON reports 87.87480907848548% total
  coverage with 2471 missing lines, and `evm.py` is up to
  87.01707097933513% with 284 missing lines. The remaining below-100% files
  are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_local_initializer_and_lvalue_diagnostics_are_reported_by_bytecode
  -v`: passed after adding source-level EVM diagnostics for unsupported local
  object types and scalar initialization of aggregate locals.
- `uv run tox -e py311`: passed after the EVM local diagnostic coverage; the
  coverage JSON reports 87.8855274793001% total coverage with 2469 missing
  lines, and `evm.py` is up to 87.10691823899371% with 282 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_default_returns_emit_zero_values_for_non_integer_result_types
  tests.test_codegen.CodegenTests.test_grouped_global_declarations_emit_each_object
  -v`: passed after adding executable LLVM coverage for implicit default
  returns of pointer, floating, and record-returning functions plus grouped
  file-scope declarations that emit multiple global objects.
- `uv run tox -e py311`: passed after the LLVM default-return and grouped
  global declaration coverage; the coverage JSON reports 87.91500308154023%
  total coverage with 2464 missing lines, and `codegen.py` is up to
  78.14520598559025% with 635 missing lines. The remaining below-100% files
  are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_local_initializer_designators_and_void_return_execute
  tests.test_codegen.CodegenTests.test_control_flow_comma_and_string_literal_cache_execute
  -v`: passed after adding executable LLVM coverage for explicit `return;`,
  null statements, local initializer designators, integer-to-`_Bool` calls,
  block-scope typedef/static assert statements, comma expressions, repeated
  string literal caching, and wide string literal expressions.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_grouped_globals_and_static_locals_emit_each_object
  tests.test_aarch64_asm.AArch64AsmTests.test_grouped_globals_and_static_locals_emit_each_object
  -v`: passed after adding native backend coverage for grouped file-scope
  globals and grouped static locals in x86_64 and Darwin AArch64 assembly
  output.
- `uv run tox -e py311`: passed after the LLVM local/control-flow coverage and
  native backend grouped declaration coverage; the coverage JSON reports
  88.23655510597818% total coverage with 2399 missing lines, `codegen.py` is
  up to 78.42231664511361% with 627 missing lines, `x86_64_asm.py` is up to
  78.06206668867613% with 756 missing lines, and `aarch64_asm.py` is up to
  81.27750177430802% with 734 missing lines. The remaining below-100% files
  are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_global_union_and_bitfield_initializers_emit_storage_units
  tests.test_x86_64_asm.X86_64AsmTests.test_record_compound_literal_initializes_bitfields_and_array_members
  tests.test_x86_64_asm.X86_64AsmTests.test_bitfield_member_compound_assignment_and_updates_emit_masks
  tests.test_aarch64_asm.AArch64AsmTests.test_record_compound_literal_assignment_initializes_array_field
  -v`: passed after adding x86_64 assembly coverage for global union padding,
  global bit-field storage-unit initialization, record compound literal
  bit-field/array-member initialization, and bit-field compound/update masks,
  plus Darwin AArch64 execution coverage for record compound literals
  initializing scalar array members and arrays of record members.
- `uv run tox -e py311`: passed after the native backend bit-field and
  compound-literal coverage; the coverage JSON reports 88.72424234304242%
  total coverage with 2269 missing lines, `x86_64_asm.py` is up to
  80.30703202377022% with 657 missing lines, and `aarch64_asm.py` is up to
  81.930447125621% with 703 missing lines. The remaining below-100% files are
  still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_global_array_initializer_accepts_sparse_index_designators
  tests.test_x86_64_asm.X86_64AsmTests.test_nested_offsetof_member_path_folds_to_constant
  tests.test_x86_64_asm.X86_64AsmTests.test_local_incomplete_arrays_infer_initializer_storage
  -v`: passed after adding x86_64 assembly coverage for sparse global array
  designators, nested `offsetof` member paths, and local incomplete array
  initializer storage.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_sizeof_member_chains_and_nested_offsetof_execute
  -v`: passed after adding Darwin AArch64 execution coverage for chained
  member `sizeof`, nested `offsetof`, and global member sizing.
- `uv run tox -e py311`: passed after the x86_64 sparse designator/local array
  coverage and AArch64 member-chain coverage; the coverage JSON reports
  88.9225327581125% total coverage with 2221 missing lines,
  `aarch64_asm.py` is up to 81.95883605393897% with 702 missing lines,
  `codegen.py` remains at 78.42231664511361% with 627 missing lines,
  `evm.py` remains at 87.10691823899371% with 282 missing lines, and
  `x86_64_asm.py` is up to 81.49554308352592% with 610 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_unused_inline_body_is_not_emitted
  tests.test_x86_64_asm.X86_64AsmTests.test_referenced_inline_function_designators_are_emitted
  tests.test_x86_64_asm.X86_64AsmTests.test_stack_aggregate_parameter_spills_float_and_integer_chunks
  tests.test_aarch64_asm.AArch64AsmTests.test_global_pointer_initializer_accepts_extern_object_symbol
  -v`: passed after adding x86_64 assembly coverage for unused inline
  suppression, referenced inline function designators, and stack-passed
  aggregate parameter chunks, plus AArch64 coverage for global pointer
  initializers that reference extern object symbols.
- `uv run tox -e py311`: passed after the inline/ABI/native global pointer
  coverage; the coverage JSON reports 89.00292076422198% total coverage with
  2203 missing lines, `aarch64_asm.py` is up to 82.05819730305181% with
  698 missing lines, `codegen.py` remains at 78.42231664511361% with
  627 missing lines, `evm.py` remains at 87.10691823899371% with
  282 missing lines, and `x86_64_asm.py` is up to 81.87520633872565% with
  596 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_block_scope_externs_void_return_and_terminator_edges_execute
  tests.test_codegen.CodegenTests.test_unprototyped_function_pointer_initializer_executes
  -v`: passed after adding executable LLVM coverage for block-scope `extern`
  scalar/array reads, void expression returns, nested scalar brace
  initializers, forward `goto`, endless `for` plus `break`, post-return alloca
  insertion, and unprototyped function-pointer initialization.
- `uv run tox -e py311`: passed after the LLVM codegen edge coverage; the
  coverage JSON reports 89.04847396768402% total coverage with 2194 missing
  lines, `aarch64_asm.py` remains at 82.05819730305181% with
  698 missing lines, `codegen.py` is up to 78.73637539257344% with
  618 missing lines, `evm.py` remains at 87.10691823899371% with
  282 missing lines, and `x86_64_asm.py` remains at 81.87520633872565% with
  596 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_union_layout_keeps_tail_padding_from_largest_alignment
  tests.test_x86_64_asm.X86_64AsmTests.test_statement_slot_collection_handles_else_for_expr_and_static_assert
  tests.test_aarch64_asm.AArch64AsmTests.test_global_integer_initializer_accepts_cpython_version_pack_calls
  tests.test_aarch64_asm.AArch64AsmTests.test_global_record_initializer_handles_union_bitfield_flex_and_zero_edges
  -v`: passed after adding public-path coverage for alignment-driven LLVM union
  tail padding, x86_64 else/for/static-assert slot collection, and Darwin
  AArch64 CPython version-pack plus global union/bit-field/flexible-array
  initializer edges.
- `uv run tox -e py311`: passed after the backend initializer/layout coverage;
  the coverage JSON reports 89.27623998499423% total coverage with
  2137 missing lines, `aarch64_asm.py` is up to 83.02342086586232% with
  650 missing lines, `codegen.py` is up to 78.81027156844634% with
  616 missing lines, `evm.py` remains at 87.10691823899371% with
  282 missing lines, and `x86_64_asm.py` is up to 82.08979861340376% with
  589 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_float_logical_not_uses_unordered_zero_compare
  tests.test_x86_64_asm.X86_64AsmTests.test_int_division_and_bitwise_not_use_sized_integer_ops
  tests.test_x86_64_asm.X86_64AsmTests.test_bitfield_postfix_update_preserves_old_result
  tests.test_codegen.CodegenTests.test_record_char_array_member_string_initializer_stores_array_value
  -v`: passed after adding x86_64 floating logical-not, 32-bit division,
  bitwise-not, and bit-field postfix old-result coverage plus executable LLVM
  coverage for `char[]` record-member string initialization.
- `uv run tox -e py311`: passed after the x86_64/codegen coverage additions;
  the coverage JSON reports 89.34590959028912% total coverage with
  2118 missing lines, `aarch64_asm.py` remains at 83.02342086586232% with
  650 missing lines, `codegen.py` is up to 78.88416774431923% with
  613 missing lines, `evm.py` remains at 87.10691823899371% with
  282 missing lines, and `x86_64_asm.py` is up to 82.45295477055134% with
  573 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_float_conditions_branch_on_unordered_nonzero
  tests.test_x86_64_asm.X86_64AsmTests.test_pointer_difference_scales_by_element_size
  tests.test_x86_64_asm.X86_64AsmTests.test_member_access_of_aggregate_call_results_uses_temporary_storage
  tests.test_codegen.CodegenTests.test_member_access_of_aggregate_call_results_executes
  -v`: passed after adding x86_64 native coverage for unordered floating
  condition branches, pointer subtraction element-size scaling, and temporary
  storage for member access on aggregate call results, plus executable LLVM
  coverage for small/direct and large/indirect aggregate call-result member
  reads.
- `uv run tox -e py311`: passed after the aggregate call-result and x86_64
  branch/scaling coverage; the coverage JSON reports
  89.44773439802782% total coverage with 2089 missing lines,
  `aarch64_asm.py` remains at 83.02342086586232% with 650 missing lines,
  `codegen.py` is up to 79.10585627193792% with 605 missing lines,
  `evm.py` remains at 87.10691823899371% with 282 missing lines, and
  `x86_64_asm.py` is up to 82.88213931990757% with 552 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`.
- `uv run tox -e cpython-build -- "$cpython_src"` passed against a clean
  temporary CPython worktree at `/tmp/xcc-cpython-src.KycKXo`, running
  `configure && make -j8` with `.tox/cpython-build/bin/xcc`. The build checked
  116 modules, built 37 built-in and 78 shared modules, reported `_gdbm`
  missing only from local dependencies, and had 0 failed imports.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_builtin_va_copy_reads_copied_variadic_cursor
  tests.test_codegen.CodegenTests.test_scalar_aggregate_initializers_store_first_member
  tests.test_x86_64_asm.X86_64AsmTests.test_global_double_initializer_folds_float_constant_forms
  tests.test_x86_64_asm.X86_64AsmTests.test_builtin_isnan_lowers_without_external_call
  -v`: failed before the LLVM aggregate-scalar initializer fix with invalid
  scalar-to-record LLVM IR, then failed with an uninitialized omitted member,
  then passed after local aggregate declarations routed through
  initializer-to-address lowering and scalar aggregate initialization zeroed
  the destination before initializing the first member.
- `uv run tox -e py311`: passed after the `__builtin_va_copy`, scalar
  aggregate initializer, x86_64 `__builtin_isnan`, and floating constant
  initializer coverage additions; the coverage JSON reports
  89.68304957704251% total coverage with 2035 missing lines,
  `aarch64_asm.py` remains at 83.02342086586232% with 650 missing lines,
  `codegen.py` is up to 79.85321100917432% with 581 missing lines,
  `evm.py` remains at 87.10691823899371% with 282 missing lines, and
  `x86_64_asm.py` is up to 83.72400132056785% with 522 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`, and the ratchet is tightened to 89.68%.
- `uv run coverage report --fail-under=89.68`: passed after the ratchet
  update.
- `uv run tox -e mypyc,lint,type`: passed after the ratchet update; the mypyc
  env rebuilt `build/mypyc/lib`, ran the full test suite through the compiled
  import tree, and then `ruff`, `ty`, and `mypy` passed.
- `uv run pre-commit run --all-files`: passed after the ratchet update,
  including the local test, lint, and type gates.
- `git diff --check`: passed after the ratchet update.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_global_range_designators_initialize_arrays_and_nested_arrays
  tests.test_x86_64_asm.X86_64AsmTests.test_extended_common_gcc_builtins_cover_inline_x86_paths
  tests.test_aarch64_asm.AArch64AsmTests.test_builtin_variants_emit_inline_aarch64_text_paths
  -v`: passed after adding LLVM global range-designator execution coverage
  and native text coverage for extended x86_64 and AArch64 builtin paths.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_initcode_evaluates_generic_types_chars_and_cast_function_labels
  -v`: passed after adding EVM initcode/runtime coverage for storage
  `_Generic`, `__builtin_types_compatible_p`, multi-character constants, octal
  constants, and cast function-pointer labels.
- `uv run tox -e py311`: passed after the native builtin, range-designator,
  and EVM storage-constant coverage additions; the coverage JSON reports
  89.97215976014563% total coverage with 1962 missing lines,
  `aarch64_asm.py` is up to 83.77572746628815% with 611 missing lines,
  `codegen.py` is up to 80.20183486238533% with 569 missing lines,
  `evm.py` is up to 87.53369272237197% with 271 missing lines, and
  `x86_64_asm.py` is up to 84.00462198745461% with 511 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`, and the ratchet is tightened to 89.97%.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_global_initializer_variants_emit_constants_designators_and_compounds
  tests.test_x86_64_asm.X86_64AsmTests.test_mixed_aggregate_return_and_call_argument_use_fp_and_integer_chunks
  tests.test_x86_64_asm.X86_64AsmTests.test_static_aggregate_identifier_and_func_name_literal_emit_addresses
  -v`: passed after adding AArch64 global initializer variant coverage and
  x86_64 mixed aggregate ABI plus C11 `__func__`/static aggregate identifier
  coverage.
- `uv run tox -e py311`: passed after the AArch64 global initializer and x86_64
  mixed aggregate/`__func__` coverage additions; the coverage JSON reports
  90.04979119820109% total coverage with 1942 missing lines,
  `aarch64_asm.py` is up to 83.90347764371894% with 605 missing lines,
  `codegen.py` remains at 80.20183486238533% with 569 missing lines,
  `evm.py` remains at 87.53369272237197% with 271 missing lines, and
  `x86_64_asm.py` is up to 84.33476394849785% with 497 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`, and the ratchet is tightened to 90.05%.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_runtime_binary_literal_and_pointer_variants_execute
  tests.test_codegen.CodegenTests.test_aggregate_initializers_accept_comma_and_conditional_whole_values
  -v`: passed after adding EVM execution coverage for binary
  comparison/bitwise variants, pointer subtraction assignment, string-literal
  expressions, scalar and fixed-array compound literals, plus executable LLVM
  coverage for comma and conditional whole-aggregate initializers.
- `uv run tox -e py311`: passed after the EVM and LLVM aggregate coverage
  additions; the coverage JSON reports 90.08994539029875% total coverage with
  1933 missing lines, `aarch64_asm.py` remains at 83.90347764371894% with
  605 missing lines, `codegen.py` is up to 80.23853211009174% with
  568 missing lines, `evm.py` is up to 87.82569631626235% with
  263 missing lines, and `x86_64_asm.py` remains at 84.33476394849785% with
  497 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 90.09%.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_sizeof_and_alignof_use_evm_word_object_layout_without_side_effects
  tests.test_evm.EvmTargetTests.test_initcode_evaluates_storage_constant_expression_operators
  -v`: passed after extending EVM runtime coverage for anonymous record sizing
  and member access, plus EVM initcode coverage for nested conditional
  constants, `sizeof`, `_Alignof`, `__builtin_offsetof`,
  `__builtin_types_compatible_p`, `_Generic`, and narrow casts.
- `uv run tox -e py311`: passed after the EVM constant-expression and anonymous
  record coverage additions; the coverage JSON reports 90.20237712817219%
  total coverage with 1911 missing lines, `aarch64_asm.py` remains at
  83.90347764371894% with 605 missing lines, `codegen.py` remains at
  80.23853211009174% with 568 missing lines, `evm.py` is up to
  88.76909254267744% with 241 missing lines, and `x86_64_asm.py` remains at
  84.33476394849785% with 497 missing lines. The remaining below-100% files
  are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and
  the ratchet is tightened to 90.20%.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_local_unbraced_nested_aggregate_initializers_consume_member_items
  tests.test_codegen.CodegenTests.test_mixed_float_arithmetic_and_compound_assignments_execute
  tests.test_codegen.CodegenTests.test_switch_case_unary_conditional_and_comma_constants_fold
  tests.test_codegen.CodegenTests.test_global_designator_indexes_fold_unary_conditional_and_comma_constants
  -v`: passed after adding LLVM execution coverage for local flattened nested
  aggregate initialization, mixed float arithmetic, switch case constants, and
  global designator constant indexes.
- `uv run tox -e py311`: passed after the LLVM codegen coverage additions and
  switch case constant-expression fix; the coverage JSON reports
  90.352708199529% total coverage with 1879 missing lines,
  `aarch64_asm.py` remains at 83.90347764371894% with 605 missing lines,
  `codegen.py` is up to 81.28890516294398% with 536 missing lines, `evm.py`
  remains at 88.76909254267744% with 241 missing lines, and
  `x86_64_asm.py` remains at 84.33476394849785% with 497 missing lines. The
  remaining below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`,
  `codegen.py`, and `evm.py`, and the ratchet is tightened to 90.35%.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_bitfield_aggregate_return_keeps_integer_and_fp_chunks
  tests.test_codegen.CodegenTests.test_global_nested_designators_initialize_named_and_anonymous_members
  -v`: passed after adding x86_64 bit-field aggregate ABI coverage and LLVM
  global nested-designator execution coverage.
- `uv run tox -e py311`: passed after the x86_64 aggregate ABI coverage
  addition; the coverage JSON reports 90.40087775636908% total coverage with
  1865 missing lines, `aarch64_asm.py` remains at 83.90347764371894% with
  605 missing lines, `codegen.py` remains at 81.28890516294398% with
  536 missing lines, `evm.py` remains at 88.76909254267744% with
  241 missing lines, and `x86_64_asm.py` is up to 84.63189171343677% with
  483 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 90.40%.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_record_compound_literal_initializes_bitfields_and_array_members
  tests.test_aarch64_asm.AArch64AsmTests.test_global_record_initializer_handles_union_bitfield_flex_and_zero_edges
  tests.test_aarch64_asm.AArch64AsmTests.test_record_compound_literal_skips_unnamed_bitfields_positionally`:
  failed before the native initializer fix because unnamed zero-width
  bit-fields consumed positional initializer slots, then passed after x86_64
  and AArch64 skip unnamed bit-fields during positional record initializer
  mapping.
- `uv run tox -e py311`: passed after the unnamed bit-field positional
  initializer fix; the coverage JSON reports 90.41264407776856% total coverage
  with 1862 missing lines, `aarch64_asm.py` is up to 83.93312553131199% with
  605 missing lines, `codegen.py` remains at 81.28890516294398% with
  536 missing lines, `evm.py` remains at 88.76909254267744% with
  241 missing lines, and `x86_64_asm.py` is up to 84.69522240527183% with
  480 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 90.41%.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_statement_expression_void_forms_and_static_scalar_local_compile
  tests.test_x86_64_asm.X86_64AsmTests.test_va_start_accounts_for_aggregate_and_float_fixed_parameters
  tests.test_x86_64_asm.X86_64AsmTests.test_pointer_right_add_and_void_cast_expression_paths
  tests.test_x86_64_asm.X86_64AsmTests.test_float_compound_and_cast_paths_emit_expected_conversions
  -v`: passed after adding x86_64 public-path coverage for statement-expression,
  varargs, pointer/cast, and float conversion paths. The existing x86_64 builtin,
  address, and float-condition tests were also extended for bswap/ctz/long-double
  constants, function/static-local addresses, and unordered floating `!=`.
- `COVERAGE_FILE=/tmp/.coverage-xcc-x86-next uv run coverage run -m unittest
  tests.test_x86_64_asm` plus `coverage json --fail-under=0`: passed and
  measured `src/xcc/x86_64_asm.py` at 85.40362438220758% with 454 missing
  lines, down from 480 missing lines at the previous full gate.
- `uv run tox -e py311`: passed after the x86_64 public-path coverage additions;
  the coverage JSON reports 90.52763886288878% total coverage with
  1836 missing lines, `aarch64_asm.py` remains at 83.93312553131199% with
  605 missing lines, `codegen.py` remains at 81.28890516294398% with
  536 missing lines, `evm.py` remains at 88.76909254267744% with
  241 missing lines, and `x86_64_asm.py` is up to 85.40362438220758% with
  454 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 90.52%.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_codegen_helper_fallback_paths_are_covered_without_llc
  tests.test_codegen.CodegenTests.test_codegen_helper_control_and_initializer_edges_without_llc
  -v`: passed after adding low-cost direct LLVM backend helper coverage for
  defensive fallback edges that valid C source cannot naturally reach after
  sema validation.
- `COVERAGE_FILE=/tmp/.coverage-xcc-codegen-helper2 uv run coverage run -m
  unittest tests.test_codegen` plus `coverage json --fail-under=0`: passed and
  measured `src/xcc/codegen.py` at 83.41266935188575% with 475 missing lines,
  down from 536 missing lines at the previous full gate.
- `uv run tox -e py311`: passed after the codegen helper coverage additions; the
  coverage JSON reports 90.8378573529805% total coverage with 1775 missing
  lines, `aarch64_asm.py` remains at 83.93312553131199% with 605 missing lines,
  `codegen.py` is up to 83.41266935188575% with 475 missing lines, `evm.py`
  remains at 88.76909254267744% with 241 missing lines, and `x86_64_asm.py`
  remains at 85.40362438220758% with 454 missing lines. The remaining below-100%
  files are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and
  `evm.py`, and the ratchet is tightened to 90.83%.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_codegen_helper_unary_builtin_and_call_edges_without_llc
  -v`: passed after adding direct LLVM helper coverage for unary fallback,
  address-of fallback, malformed builtin arity fallback, indirect call errors,
  and member/global lookup edges.
- `COVERAGE_FILE=/tmp/.coverage-xcc-codegen-helper3 uv run coverage run -m
  unittest tests.test_codegen` plus `coverage json --fail-under=0`: passed and
  measured `src/xcc/codegen.py` at 85.60966678872208% with 411 missing lines.
- `uv run python -m unittest
  tests.test_codegen.CodegenTests.test_codegen_helper_constant_initializer_edges_without_llc
  -v`: initially exposed a wrong test expectation for nonconstant designator
  length inference, then passed after aligning the assertion with the helper's
  sequential fallback semantics.
- `COVERAGE_FILE=/tmp/.coverage-xcc-codegen-helper4 uv run coverage run -m
  unittest tests.test_codegen` plus `coverage json --fail-under=0`: passed and
  measured `src/xcc/codegen.py` at 89.54595386305382% with 288 missing lines.
- `uv run tox -e py311`: passed after the unary/builtin/call and constant
  initializer helper coverage additions; the coverage JSON reports
  91.7337469579868% total coverage with 1588 missing lines,
  `aarch64_asm.py` remains at 83.93312553131199% with 605 missing lines,
  `codegen.py` is up to 89.54595386305382% with 288 missing lines, `evm.py`
  remains at 88.76909254267744% with 241 missing lines, and `x86_64_asm.py`
  remains at 85.40362438220758% with 454 missing lines. The remaining below-100%
  files are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and
  `evm.py`, and the ratchet is tightened to 91.72%.
- `uv run tox -e cpython-build -- ../cpython`: failed before compiling because
  CPython rejected the default source checkout as not clean for out-of-tree
  builds. Git status had no ordinary tracked/untracked changes, so the likely
  cause was ignored source-tree build artifacts; the checkout was not cleaned.
- `uv run tox -e cpython-build -- build/cpython-src-clean`: passed on the clean
  detached CPython worktree. The gate rebuilt XCC through mypyc, ran CPython
  `configure`, then completed `make -j8`; 116 modules were checked, 37 were
  built-in, 78 were shared, `_gdbm` was the only missing module from local
  dependencies, and 0 modules failed on import.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_evm_assembler_encodes_negative_values_and_push0
  tests.test_evm.EvmTargetTests.test_evm_helper_function_shape_edges
  tests.test_evm.EvmTargetTests.test_evm_helper_abi_and_record_diagnostics
  tests.test_evm.EvmTargetTests.test_evm_helper_control_layout_and_type_edges
  tests.test_evm.EvmTargetTests.test_evm_helper_type_spec_and_storage_initializer_edges
  -v`: passed after adding fast EVM helper coverage for backend-only assembler,
  function-shape, ABI, record, control-flow, type-spec, and storage-initializer
  edges.
- `uv run python -m unittest tests.test_evm -v`: passed after the EVM helper
  coverage additions with 111 tests.
- `uv run tox -e py311`: passed after the EVM helper coverage additions; the
  coverage JSON reports 92.01722247479475% total coverage with
  1532 missing lines, `aarch64_asm.py` remains at 83.93312553131199% with
  605 missing lines, `codegen.py` remains at 89.54595386305382% with
  288 missing lines, `evm.py` is up to 91.15004492362984% with
  185 missing lines, and `x86_64_asm.py` remains at 85.40362438220758% with
  454 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 92.01%.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_evm_helper_constant_expression_and_initcode_edges
  tests.test_evm.EvmTargetTests.test_evm_helper_memory_initializer_diagnostics
  -v`: passed after adding EVM helper coverage for constant-expression
  fallbacks, initcode size checks, PUSH operand bounds, bit-field truncation,
  storage stores, and memory initializer diagnostics.
- `uv run python -m unittest tests.test_evm -v`: passed after the second EVM
  helper coverage sweep with 113 tests.
- `COVERAGE_FILE=/tmp/.coverage-xcc-evm-helper-next uv run coverage run -m
  unittest tests.test_evm` plus `coverage json --fail-under=0`: passed and
  measured `src/xcc/evm.py` at 92.6774483378257% with 148 missing lines.
- `uv run tox -e py311`: passed after the second EVM helper coverage sweep; the
  coverage JSON reports 92.19907469312439% total coverage with
  1495 missing lines, `aarch64_asm.py` remains at 83.93312553131199% with
  605 missing lines, `codegen.py` remains at 89.54595386305382% with
  288 missing lines, `evm.py` is up to 92.6774483378257% with
  148 missing lines, and `x86_64_asm.py` remains at 85.40362438220758% with
  454 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 92.19%.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_evm_helper_designator_and_storage_initializer_edges
  -v`: passed after adding EVM helper coverage for memory/storage initializer
  designator diagnostics, bounds checks, string local initializer targets,
  `_Generic` selection failures, `sizeof` operand type failures, array
  alignment, and pointer-stride helpers.
- `uv run python -m unittest tests.test_evm -v`: passed after the EVM
  designator/storage helper coverage addition with 114 tests.
- `COVERAGE_FILE=/tmp/.coverage-xcc-evm-designators uv run coverage run -m
  unittest tests.test_evm` plus `coverage json --fail-under=0`: passed and
  measured `src/xcc/evm.py` at 94.07008086253369% with 117 missing lines.
- `uv run tox -e py311`: passed after the EVM designator/storage helper
  coverage addition; one standalone run measured 92.36488112748376% total
  coverage with 1464 missing lines.
- `uv run pre-commit run --all-files`: initially showed the 92.36% ratchet was
  too tight for the submission path; its py311 coverage run measured
  92.35150964084187% total coverage with 1467 missing lines,
  `aarch64_asm.py` at 83.93312553131199% with 605 missing lines, `codegen.py`
  at 89.45441230318565% with 291 missing lines, `evm.py` at
  94.07008086253369% with 117 missing lines, and `x86_64_asm.py` at
  85.40362438220758% with 454 missing lines. The remaining below-100% files are
  still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to the stable pre-commit value 92.35%.
- `uv run coverage report --fail-under=92.35`: passed after lowering the
  ratchet to the pre-commit-measured value.
- `uv run pre-commit run --all-files`: passed after lowering the ratchet to
  92.35%.
- `uv run python -m unittest
  tests.test_evm.EvmTargetTests.test_evm_helper_return_switch_and_conversion_edges
  tests.test_evm.EvmTargetTests.test_evm_helper_expression_assignment_and_lvalue_edges
  tests.test_evm.EvmTargetTests.test_evm_helper_call_layout_edges -v`: passed
  after adding the next EVM helper coverage sweep for return layouts, switch
  misuse, expression/lvalue diagnostics, aggregate assignment mismatch paths,
  casts, statement/comma expressions, and direct/indirect function-call layout
  errors.
- `uv run python -m unittest tests.test_evm -v`: passed after the EVM helper
  coverage sweep with 117 tests.
- `COVERAGE_FILE=/tmp/.coverage-xcc-evm-next uv run coverage run -m unittest
  tests.test_evm` plus `coverage json --fail-under=0`: passed and measured
  `src/xcc/evm.py` at 96.13656783468105% with 71 missing lines.
- `uv run tox -e py311`: passed after the EVM helper coverage sweep; the
  coverage JSON reports 92.61091648169443% total coverage with 1418 missing
  lines, `aarch64_asm.py` remains at 83.93312553131199% with
  605 missing lines, `codegen.py` remains at 89.54595386305382% with
  288 missing lines, `evm.py` is up to 96.13656783468105% with
  71 missing lines, and `x86_64_asm.py` remains at 85.40362438220758% with
  454 missing lines. The remaining below-100% files are still
  `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 92.60%.
- `uv run python -m unittest tests.test_run_tests -v`: passed after updating
  the ratchet contract test to 92.60%.
- `uv run coverage report --fail-under=92.60`: passed after the ratchet update.
- `uv run tox -e mypyc,lint,type`: passed after the EVM helper coverage and
  ratchet updates; the mypyc gate rebuilt XCC and ran all 17 test modules with
  8 workers against `build/mypyc/lib`.
- `uv run tox -e lint` and `uv run tox -e type`: both passed as explicit
  handoff gates.
- `uv run pre-commit run --all-files`: passed with the 92.60% ratchet.
- `uv run coverage json -o /tmp/xcc-coverage-final-92-60.json --fail-under=0`:
  passed after final pre-commit runs. The submission path has measured
  92.60556788703768%-92.61091648169443% total coverage with 1418-1419 missing
  lines because one codegen line is worker-order-sensitive; the 92.60% ratchet
  remains below the observed lower bound. `evm.py` stays at
  96.13656783468105% with 71 missing lines.
- `git diff --check`: passed after the final gate run.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_global_integer_initializer_folds_constant_expression_matrix
  tests.test_x86_64_asm.X86_64AsmTests.test_global_integer_initializer_folds_constant_expression_matrix
  -v`: passed after adding public-path native backend initializer coverage.
- `COVERAGE_FILE=/tmp/.coverage-xcc-backend-const uv run coverage run -m
  unittest tests.test_aarch64_asm tests.test_x86_64_asm -v` plus `coverage
  json --fail-under=0`: passed. Compared with the previous full coverage JSON,
  the new initializer matrix covers 30 old AArch64 missing lines and 27 old
  x86_64 missing lines.
- `uv run tox -e py311`: passed after the native backend initializer coverage;
  the coverage JSON reports 92.9050891878159% total coverage with
  1361 missing lines, `aarch64_asm.py` at 84.74071975063758% with
  575 missing lines, `codegen.py` at 89.54595386305382% with 288 missing lines,
  `evm.py` at 96.13656783468105% with 71 missing lines, and
  `x86_64_asm.py` at 86.27677100494233% with 427 missing lines. The remaining
  below-100% files are still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`,
  and `evm.py`, and the ratchet is tightened to 92.90%.
- `uv run python -m unittest
  tests.test_x86_64_asm.X86_64AsmTests.test_global_flexible_array_member_accepts_zero_initializer
  -v`: first failed with `xcc.diag.CodegenError: test.c: codegen: x86_64
  target cannot size type int[-1]`, proving the regression test for
  zero-initialized tail flexible array globals reached the intended failure.
- `uv run python -m unittest
  tests.test_aarch64_asm.AArch64AsmTests.test_global_record_initializer_handles_flexible_zero_and_padding_edges
  tests.test_x86_64_asm.X86_64AsmTests.test_global_record_initializer_handles_flexible_zero_and_padding_edges
  -v`: passed after fixing x86_64 tail flexible array global initialization and
  adding matching public-path backend coverage for no-tail/zero-tail flexible
  arrays plus padded bit-field record layouts.
- `COVERAGE_FILE=/tmp/.coverage-xcc-flex-padding uv run coverage run -m
  unittest tests.test_aarch64_asm tests.test_x86_64_asm -v`: passed with
  313 tests and 10 host-skipped x86_64 native Linux execution tests. The
  backend coverage sample showed the new AArch64 test covers the old missing
  lines 554, 565, 592, 597, 598, and 608 in the global record initializer.
- `uv run tox -e py311`: passed after the flexible-array/padding backend
  coverage and x86_64 fix. The coverage JSON reports 92.94976338796353% total
  coverage with 1353 missing lines, `aarch64_asm.py` at
  84.92490790592235% with 569 missing lines, `codegen.py` at
  89.54595386305382% with 288 missing lines, `evm.py` at
  96.13656783468105% with 71 missing lines, and `x86_64_asm.py` at
  86.34868421052632% with 425 missing lines. The remaining below-100% files are
  still `aarch64_asm.py`, `x86_64_asm.py`, `codegen.py`, and `evm.py`, and the
  ratchet is tightened to 92.95%.
- `uv run python -m unittest tests.test_run_tests -v`: passed after updating
  the ratchet contract test to 92.95%.
- `uv run coverage report --fail-under=92.95`: passed, confirming the current
  rounded coverage report satisfies the ratchet.
