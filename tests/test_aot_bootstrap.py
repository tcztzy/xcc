import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotBootstrapRunResult,
    AotError,
    analyze_path,
    build_native_bootstrap,
    collect_bootstrap_sources,
    emit_llvm_text,
    lower_bootstrap_entry_smoke,
    lower_source_to_ir,
    plan_bootstrap_entry,
    run_bootstrap_self_host_smoke,
    summarize_bootstrap_admission,
)
from xcc.aot import slice as aot_slice

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

    def test_smoke_compiler_body_is_ordinary_lowerable(self) -> None:
        source = (ROOT / "src/xcc/cc_driver.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/cc_driver.py"),
            include_records=frozenset(),
            include_functions={"_aot_compile_smoke_source_to_object"},
        )
        function = module.functions[0]
        body = repr(function.body)
        self.assertNotIn("target='Path'", body)
        self.assertNotIn("target='str'", body)
        self.assertIn("target='_aot_read_text_file'", body)
        self.assertIn("target='_aot_write_text_file'", body)
        self.assertIn("target='_aot_exec_argv'", body)
        llvm_ir = emit_llvm_text(module)
        self.assertIn(
            "define i32 @_aot_compile_smoke_source_to_object(i32 %argc, ptr %argv)",
            llvm_ir,
        )
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %argv, i64 1)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %argv, i64 4)", llvm_ir)
        self.assertNotIn("call ptr @__getitem", llvm_ir)

    def test_bootstrap_entry_uses_project_owned_smoke_compiler(self) -> None:
        module = lower_bootstrap_entry_smoke(ROOT)
        functions = {function.name: function for function in module.functions}
        entry = functions["aot_bootstrap_smoke_main"]
        self.assertEqual(tuple(param.name for param in entry.params), ("argc", "argv"))
        self.assertIn("xcc.cc_driver._aot_compile_smoke_source_to_object", functions)
        self.assertIn("xcc.cc_driver._aot_compile_smoke_source_to_object", repr(entry.body))
        smoke_compiler = functions["xcc.cc_driver._aot_compile_smoke_source_to_object"]
        self.assertNotEqual(smoke_compiler.body, ())
        self.assertIn("target='len'", repr(smoke_compiler.body))
        self.assertIn("target='xcc.cc_driver._aot_compile_source_to_llvm_ir'", repr(smoke_compiler.body))
        self.assertNotIn("target='xcc.cc_driver._aot_is_smoke_source'", repr(smoke_compiler.body))
        self.assertNotIn("target='xcc.cc_driver._aot_smoke_llvm_ir'", repr(smoke_compiler.body))
        self.assertIn("xcc.cc_driver._aot_compile_source_to_llvm_ir", functions)
        self.assertIn("xcc.cc_driver._aot_is_smoke_compile_command", functions)
        self.assertIn("xcc.cc_driver._aot_smoke_llvm_path", functions)
        self.assertIn("xcc.cc_driver._aot_smoke_llc_argv", functions)
        self.assertIn("xcc.cc_driver._aot_read_text_file", functions)
        self.assertIn("xcc.cc_driver._aot_write_text_file", functions)
        self.assertIn("xcc.cc_driver._aot_exec_argv", functions)

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define i32 @main(i32 %argc, ptr %argv)", llvm_ir)
        self.assertIn(
            "%argv_tuple = call ptr @__xcc_aot_c_argv_to_tuple(i32 %argc, ptr %argv)",
            llvm_ir,
        )
        self.assertIn(
            "call i32 @aot_bootstrap_smoke_main(i32 %argc, ptr %argv_tuple)",
            llvm_ir,
        )
        self.assertIn("define ptr @__xcc_aot_c_argv_to_tuple(i32 %argc32, ptr %argv)", llvm_ir)
        self.assertNotIn("__xcc_aot_bootstrap_cc_delegate", llvm_ir)
        self.assertNotIn("@__xcc_aot_cc", llvm_ir)
        self.assertIn(
            "define i32 @xcc.cc_driver._aot_compile_smoke_source_to_object(i32 %argc, ptr %argv)",
            llvm_ir,
        )
        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %argv)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %argv, i64 1)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %argv, i64 2)", llvm_ir)
        self.assertNotIn("load_args:", llvm_ir)
        self.assertNotIn("write_llvm_path:", llvm_ir)
        self.assertNotIn("exec_llc:", llvm_ir)
        self.assertNotIn("%arg1_slot = getelementptr ptr, ptr %argv, i64 1", llvm_ir)
        self.assertNotIn("%arg4_slot = getelementptr ptr, ptr %argv, i64 4", llvm_ir)
        self.assertIn("define ptr @xcc.cc_driver._aot_read_text_file(ptr %path)", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_read_text_file(ptr %path)", llvm_ir)
        self.assertIn(
            "call ptr @xcc.cc_driver._aot_read_text_file(ptr %",
            llvm_ir,
        )
        self.assertIn(
            "define i1 @xcc.cc_driver._aot_is_smoke_compile_command("
            "i32 %argc, ptr %c_flag, ptr %output_flag)",
            llvm_ir,
        )
        self.assertIn(
            "call i1 @xcc.cc_driver._aot_is_smoke_compile_command("
            "i32 %argc, ptr %",
            llvm_ir,
        )
        self.assertNotIn("%arg1_cmp = call i32 @strcmp", llvm_ir)
        self.assertNotIn("%arg3_cmp = call i32 @strcmp", llvm_ir)
        self.assertIn(
            "define ptr @xcc.cc_driver._aot_compile_source_to_llvm_ir("
            "ptr %source_path, ptr %source_text)",
            llvm_ir,
        )
        self.assertIn(
            "call ptr @xcc.cc_driver._aot_compile_source_to_llvm_ir(ptr %",
            llvm_ir,
        )
        self.assertNotIn("%source_file = call ptr @fopen", llvm_ir)
        self.assertNotIn("%source_read = call i64 @fread", llvm_ir)
        self.assertNotIn("%source_len_ok = icmp eq i64 %source_read, 26", llvm_ir)
        self.assertNotIn("call i32 @strcmp(ptr %source, ptr null)", llvm_ir)
        self.assertIn("define ptr @xcc.cc_driver._aot_smoke_llvm_path(ptr %object_path)", llvm_ir)
        self.assertIn("call ptr @xcc.cc_driver._aot_smoke_llvm_path(ptr %", llvm_ir)
        self.assertNotIn("%ll_path_written = call i32", llvm_ir)
        self.assertNotIn("%s.ll", llvm_ir)
        self.assertIn(
            "define i1 @xcc.cc_driver._aot_write_text_file(ptr %path, ptr %text)",
            llvm_ir,
        )
        self.assertIn("define i1 @__xcc_aot_write_text_file(ptr %path, ptr %text)", llvm_ir)
        self.assertIn(
            "call i1 @xcc.cc_driver._aot_write_text_file(ptr %",
            llvm_ir,
        )
        self.assertNotIn("%ll_file = call ptr @fopen", llvm_ir)
        self.assertNotIn("%llvm_written = call i64 @fwrite", llvm_ir)
        self.assertNotIn("%ll_closed = call i32 @fclose", llvm_ir)
        self.assertIn(
            "define ptr @xcc.cc_driver._aot_smoke_llc_argv("
            "ptr %llvm_path, ptr %object_path)",
            llvm_ir,
        )
        self.assertIn(
            "call ptr @xcc.cc_driver._aot_smoke_llc_argv(ptr %",
            llvm_ir,
        )
        self.assertIn("define i32 @xcc.cc_driver._aot_exec_argv(ptr %argv)", llvm_ir)
        self.assertIn("define i32 @__xcc_aot_execvp_tuple(ptr %argv_tuple)", llvm_ir)
        self.assertIn(
            "call i32 @xcc.cc_driver._aot_exec_argv(ptr %",
            llvm_ir,
        )
        self.assertIn("ret i32 %", llvm_ir)
        self.assertIn("call i32 @__xcc_aot_execvp_tuple(ptr %argv)", llvm_ir)
        self.assertNotIn("call i32 @__xcc_aot_execvp_tuple(ptr %llc_argv)", llvm_ir)
        self.assertNotIn("%llc_argv = alloca ptr, i64 6", llvm_ir)
        self.assertNotIn("call i32 @execvp(ptr @.str", llvm_ir)
        self.assertIn("/opt/homebrew/opt/llvm/bin/llc", llvm_ir)
        self.assertIn("declare ptr @fopen(ptr, ptr)", llvm_ir)
        self.assertIn("declare i64 @fwrite(ptr, i64, i64, ptr)", llvm_ir)
        self.assertIn("declare i32 @execvp(ptr, ptr)", llvm_ir)

    def test_source_to_llvm_unchecked_helper_body_is_ordinary_lowerable(self) -> None:
        source = (ROOT / "src/xcc/cc_driver.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/cc_driver.py"),
            include_records=frozenset(),
            include_functions={"_aot_compile_source_to_llvm_ir_unchecked"},
            extra_classes={
                **analyze_path(ROOT / "src/xcc/frontend.py").types.classes,
                **analyze_path(ROOT / "src/xcc/options.py").types.classes,
            },
        )
        self.assertEqual(len(module.functions), 1)
        helper = module.functions[0]
        body = repr(helper.body)
        self.assertIn("target='_aot_compile_source_unchecked'", body)
        self.assertNotIn("target='compile_source'", body)
        self.assertIn("target='generate_llvm_ir'", body)

    def test_codegen_generate_lowers_module_print_boundary(self) -> None:
        class_types = {}
        for module_path in (
            ROOT / "src/xcc/ast.py",
            ROOT / "src/xcc/frontend.py",
            ROOT / "src/xcc/sema/symbols.py",
        ):
            class_types.update(analyze_path(module_path).types.classes)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen.generate", "_llvm_print_module_to_string"},
            bodyless_functions={"_llvm_print_module_to_string"},
            extra_classes=class_types,
        )
        functions = {function.name: function for function in module.functions}
        self.assertIn("_LLVMGen.generate", functions)
        self.assertIn("_llvm_print_module_to_string", functions)
        self.assertIn(
            "target='_llvm_print_module_to_string'",
            repr(functions["_LLVMGen.generate"].body),
        )

    def test_frontend_unchecked_success_helper_body_is_ordinary_lowerable(self) -> None:
        class_types = {}
        for module_path in (
            ROOT / "src/xcc/ast.py",
            ROOT / "src/xcc/frontend.py",
            ROOT / "src/xcc/lexer.py",
            ROOT / "src/xcc/options.py",
            ROOT / "src/xcc/preprocessor/__init__.py",
            ROOT / "src/xcc/sema/symbols.py",
        ):
            class_types.update(analyze_path(module_path).types.classes)
        source = (ROOT / "src/xcc/frontend.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/frontend.py"),
            include_records=frozenset(),
            include_functions={"_aot_compile_source_unchecked"},
            extra_classes=class_types,
        )
        self.assertEqual(len(module.functions), 1)
        body = repr(module.functions[0].body)
        self.assertIn("target='normalize_options'", body)
        self.assertIn("target='preprocess_source'", body)
        self.assertIn("target='lex'", body)
        self.assertIn("target='parse'", body)
        self.assertIn("target='analyze'", body)
        self.assertIn("record='FrontendResult'", body)

    def test_project_imports_are_renamed_to_qualified_slice_targets(self) -> None:
        source = (ROOT / "src/xcc/cc_driver.py").read_text(encoding="utf-8")
        rename_map = aot_slice._module_rename_map("xcc.cc_driver", source)
        self.assertEqual(
            rename_map["_aot_compile_source_unchecked"],
            "xcc.frontend._aot_compile_source_unchecked",
        )
        self.assertEqual(rename_map["generate_llvm_ir"], "xcc.codegen.generate_llvm_ir")
        edge_map = aot_slice._module_rename_map(
            "xcc.demo",
            "from pathlib import Path\n"
            "from xcc.frontend import *\n"
            "from xcc.lexer import lex as lex_tokens\n"
            "def f() -> int:\n"
            "    return 1\n",
        )
        self.assertNotIn("Path", edge_map)
        self.assertNotIn("*", edge_map)
        self.assertEqual(edge_map["lex_tokens"], "xcc.lexer.lex")


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

        with TemporaryDirectory() as temp_dir, patch("subprocess.run", fake_run):
            output = build_native_bootstrap(
                ROOT,
                Path(temp_dir) / "xcc",
                llc="/tool/llc",
                cc="cc",
            )

            self.assertEqual(output.name, "xcc")
            self.assertTrue(any(command[0] == "/tool/llc" for command in commands))
            self.assertTrue(any(command[0] == "cc" for command in commands))
            self.assertTrue((output.parent / "xcc.ll").exists())

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
            TemporaryDirectory() as temp_dir,
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            root = Path(temp_dir)
            result = run_bootstrap_self_host_smoke(root, llc="/tool/llc", cc="clang")

        self.assertIsInstance(result, AotBootstrapRunResult)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "compiled\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(builds, [(root, root / "build/aot/xcc", "/tool/llc", "clang")])
        self.assertEqual(commands[0][0], str(root / "build/aot/xcc"))

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
            TemporaryDirectory() as temp_dir,
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            result = run_bootstrap_self_host_smoke(Path(temp_dir))

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
            TemporaryDirectory() as temp_dir,
            patch("xcc.aot.bootstrap.build_native_bootstrap", fake_build),
            patch("subprocess.run", fake_run),
        ):
            result = run_bootstrap_self_host_smoke(Path(temp_dir))

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing output object", result.stderr)


if __name__ == "__main__":
    unittest.main()
