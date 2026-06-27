import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotBootstrapRunResult,
    AotError,
    build_native_bootstrap,
    collect_bootstrap_sources,
    emit_llvm_text,
    lower_bootstrap_entry_smoke,
    plan_bootstrap_entry,
    run_bootstrap_self_host_smoke,
    summarize_bootstrap_admission,
)

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

    def test_summarizes_bootstrap_admission_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "src/xcc"
            source_root.mkdir(parents=True)
            (source_root / "bad.py").write_text(
                "def bad() -> int:\n"
                "    return (lambda: 1)()\n",
                encoding="utf-8",
            )

            report = summarize_bootstrap_admission(root)

        self.assertEqual(report.total, 1)
        self.assertEqual(len(report.failed), 1)
        self.assertIn("xcc.bad", report.failed[0])
        self.assertIn("XCC-AOT-SUBSET-0001", report.failed[0])


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

    def test_entry_plan_reports_missing_bootstrap_modules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "src/xcc"
            source_root.mkdir(parents=True)
            (source_root / "__init__.py").write_text(
                "def marker() -> None:\n"
                "    return None\n",
                encoding="utf-8",
            )

            with self.assertRaises(AotError) as ctx:
                plan_bootstrap_entry(root)

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0002")
        self.assertIn("xcc.cc_driver", ctx.exception.diagnostics[0].message)


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

    def test_bootstrap_entry_uses_project_owned_smoke_compiler(self) -> None:
        module = lower_bootstrap_entry_smoke(ROOT)
        functions = {function.name: function for function in module.functions}
        entry = functions["aot_bootstrap_smoke_main"]
        self.assertEqual(tuple(param.name for param in entry.params), ("argc", "argv"))
        self.assertIn("xcc.cc_driver._aot_compile_smoke_source_to_object", functions)
        self.assertIn("xcc.cc_driver._aot_compile_smoke_source_to_object", repr(entry.body))

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define i32 @main(i32 %argc, ptr %argv)", llvm_ir)
        self.assertNotIn("__xcc_aot_bootstrap_cc_delegate", llvm_ir)
        self.assertNotIn("@__xcc_aot_cc", llvm_ir)
        self.assertIn(
            "define i32 @xcc.cc_driver._aot_compile_smoke_source_to_object(i32 %argc, ptr %argv)",
            llvm_ir,
        )
        self.assertIn("/opt/homebrew/opt/llvm/bin/llc", llvm_ir)
        self.assertIn("declare ptr @fopen(ptr, ptr)", llvm_ir)
        self.assertIn("declare i64 @fwrite(ptr, i64, i64, ptr)", llvm_ir)
        self.assertIn("declare i32 @execvp(ptr, ptr)", llvm_ir)


class AotBootstrapNativeBuildTests(unittest.TestCase):
    def test_build_native_bootstrap_invokes_llc_and_linker(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **kwargs: object) -> object:
            commands.append(tuple(command))

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            output = Path(command[-1])
            if command[0] == "/tool/llc":
                llvm_ir = Path(command[2]).read_text(encoding="utf-8")
                self.assertIn("@aot_bootstrap_smoke_main", llvm_ir)
                self.assertIn("@xcc.options.FrontendOptions.__post_init__", llvm_ir)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"out")
            if command[0] == "cc":
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"out")
            return Result()

        with patch("subprocess.run", fake_run):
            output = build_native_bootstrap(
                ROOT,
                ROOT / "build/aot/xcc",
                llc="/tool/llc",
                cc="cc",
            )

        self.assertEqual(output, ROOT / "build/aot/xcc")
        self.assertTrue(any(command[0] == "/tool/llc" for command in commands))
        self.assertTrue(any(command[0] == "cc" for command in commands))
        self.assertTrue((ROOT / "build/aot/xcc.ll").exists())

    def test_build_native_bootstrap_reports_tool_failure(self) -> None:
        def fake_run(command: tuple[str, ...], **kwargs: object) -> object:
            class Result:
                returncode = 1 if command[0] == "/tool/llc" else 0
                stdout = ""
                stderr = "llc failed"

            return Result()

        with (
            patch("subprocess.run", fake_run),
            self.assertRaises(AotError) as ctx,
        ):
            build_native_bootstrap(
                ROOT,
                ROOT / "build/aot/xcc-fail",
                llc="/tool/llc",
                cc="cc",
            )

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0003")
        self.assertEqual(ctx.exception.diagnostics[0].message, "llc failed")

    def test_real_native_bootstrap_smoke_when_llc_exists(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        output = build_native_bootstrap(ROOT, ROOT / "build/aot/xcc-smoke")
        self.assertTrue(output.exists())


class AotBootstrapSelfHostHarnessTests(unittest.TestCase):
    def test_self_host_harness_invokes_generated_executable_with_c_input(self) -> None:
        builds: list[tuple[Path, Path, str | None, str]] = []
        commands: list[tuple[str, ...]] = []

        def fake_build(
            root: Path,
            output: Path,
            *,
            llc: str | None = None,
            cc: str = "cc",
        ) -> Path:
            builds.append((root, output, llc, cc))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("#!/bin/sh\n", encoding="utf-8")
            return output

        def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess:
            commands.append(tuple(command))
            source_path = Path(command[2])
            output_path = Path(command[4])
            self.assertEqual(command[1], "-c")
            self.assertEqual(command[3], "-o")
            self.assertEqual(source_path.read_text(encoding="utf-8"), "int main(void){return 0;}\n")
            self.assertEqual(output_path.name, "self-host-smoke.o")
            output_path.write_bytes(b"object")
            return subprocess.CompletedProcess(command, 0, stdout="compiled\n", stderr="")

        with (
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            result = run_bootstrap_self_host_smoke(ROOT, llc="/tool/llc", cc="clang")

        self.assertIsInstance(result, AotBootstrapRunResult)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "compiled\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(builds, [(ROOT, ROOT / "build/aot/xcc", "/tool/llc", "clang")])
        self.assertEqual(commands[0][0], str(ROOT / "build/aot/xcc"))

    def test_self_host_harness_returns_compiler_diagnostic_status(self) -> None:
        def fake_build(
            root: Path,
            output: Path,
            *,
            llc: str | None = None,
            cc: str = "cc",
        ) -> Path:
            return output

        def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 2, stdout="", stderr="compile failed\n")

        with (
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            result = run_bootstrap_self_host_smoke(ROOT)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "compile failed\n")

    def test_self_host_harness_rejects_missing_output_object(self) -> None:
        def fake_build(
            root: Path,
            output: Path,
            *,
            llc: str | None = None,
            cc: str = "cc",
        ) -> Path:
            return output

        def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            result = run_bootstrap_self_host_smoke(ROOT)

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing output object", result.stderr)


if __name__ == "__main__":
    unittest.main()
