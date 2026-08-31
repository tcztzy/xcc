import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotBootstrapRunResult,
    AotError,
    IrBoolType,
    IrCall,
    IrModule,
    IrReturn,
    analyze_path,
    build_native_bootstrap,
    collect_bootstrap_sources,
    emit_llvm_text,
    lower_bootstrap_entry_smoke,
    plan_bootstrap_entry,
    run_bootstrap_self_host_smoke,
    summarize_bootstrap_admission,
)
from xcc.aot import slice as aot_slice
from xcc.aot.source_contract import HOSTED_ONLY_MODULES

ROOT = Path(__file__).resolve().parents[1]


class AotBootstrapGraphTests(unittest.TestCase):
    def test_source_to_llvm_wrapper_is_lowered_from_python_body(self) -> None:
        self.assertNotIn(
            "xcc.cc_driver._aot_compile_source_to_llvm_ir",
            aot_slice._NATIVE_EMITTED_LEAF_FUNCTIONS,
        )

    def test_collects_all_src_xcc_modules_in_deterministic_order(self) -> None:
        modules = collect_bootstrap_sources(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py"))) - len(HOSTED_ONLY_MODULES)
        self.assertEqual(len(modules), expected_count)
        self.assertEqual(modules[0].name, "xcc.__init__")
        self.assertIn("xcc.aot.bootstrap", {module.name for module in modules})
        self.assertTrue(HOSTED_ONLY_MODULES.isdisjoint({module.name for module in modules}))
        self.assertEqual(modules[-1].name, "xcc.x86_64_asm")

    def test_rejects_non_repository_root(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_bootstrap_sources(ROOT / "tests")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0001")

    def test_aot_v3_bootstrap_manifest_is_admitted(self) -> None:
        report = summarize_bootstrap_admission(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py"))) - len(HOSTED_ONLY_MODULES)
        self.assertEqual(report.total, expected_count)
        self.assertEqual(report.failed, ())

    def test_summarizes_bootstrap_admission_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "src/xcc"
            source_root.mkdir(parents=True)
            (source_root / "bad.py").write_text(
                "def bad() -> int:\n    return (lambda: 1)()\n",
                encoding="utf-8",
            )

            report = summarize_bootstrap_admission(root)

        self.assertEqual(report.total, 1)
        self.assertEqual(len(report.failed), 1)
        self.assertIn("xcc.bad", report.failed[0])
        self.assertIn("XCC-AOT-PARSE-0001", report.failed[0])


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

    def test_c_compiler_bootstrap_slice_excludes_aot_compiler_modules(self) -> None:
        with patch("xcc.aot.bootstrap.lower_core_entry_slice") as lower_slice:
            lower_bootstrap_entry_smoke(ROOT)

        paths = lower_slice.call_args.args[0]
        self.assertTrue(paths)
        self.assertFalse(any("/src/xcc/aot/" in str(path) for path in paths))

    def test_entry_plan_reports_missing_bootstrap_modules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "src/xcc"
            source_root.mkdir(parents=True)
            (source_root / "__init__.py").write_text(
                "def marker() -> None:\n    return None\n",
                encoding="utf-8",
            )

            with self.assertRaises(AotError) as ctx:
                plan_bootstrap_entry(root)

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0002")
        self.assertIn("xcc.cc_driver", ctx.exception.diagnostics[0].message)


class AotBootstrapLoweringTests(unittest.TestCase):
    _bootstrap_module_fixture: IrModule | None = None
    _bootstrap_llvm_fixture: str | None = None

    @classmethod
    def _lowered_bootstrap(cls) -> IrModule:
        if cls._bootstrap_module_fixture is None:
            cls._bootstrap_module_fixture = lower_bootstrap_entry_smoke(ROOT)
        return cls._bootstrap_module_fixture

    @classmethod
    def _rendered_bootstrap(cls) -> str:
        if cls._bootstrap_llvm_fixture is None:
            cls._bootstrap_llvm_fixture = emit_llvm_text(cls._lowered_bootstrap())
        return cls._bootstrap_llvm_fixture

    def test_aot_v2_full_bootstrap_fixture_is_shared(self) -> None:
        module = self._lowered_bootstrap()
        llvm_ir = self._rendered_bootstrap()

        self.assertIs(self._lowered_bootstrap(), module)
        self.assertIs(self._rendered_bootstrap(), llvm_ir)

    def test_bootstrap_compiler_path_reaches_frontend_and_codegen(self) -> None:
        module = self._lowered_bootstrap()
        functions = {function.name for function in module.functions}
        self.assertIn("xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked", functions)
        self.assertIn("xcc.frontend._aot_compile_source_unchecked", functions)
        self.assertIn("xcc.codegen.generate_llvm_ir", functions)
        self.assertIn("xcc.codegen._LLVMGen.generate", functions)

    def test_bootstrap_llvm_has_no_conftest_include_fast_path(self) -> None:
        llvm_ir = self._rendered_bootstrap()
        self.assertNotIn("conftest.c", llvm_ir)
        self.assertNotIn("#include <", llvm_ir)
        self.assertNotIn("call ptr @strstr(ptr %source_path", llvm_ir)

    def test_native_preprocessing_uses_one_exact_transaction_region(self) -> None:
        llvm_ir = self._rendered_bootstrap()
        symbol = "define i32 @xcc.preprocessor.__init__.preprocess_source_no_callback("
        start = llvm_ir.index(symbol)
        end = llvm_ir.index("\n}\n", start)
        body = llvm_ir[start:end]

        self.assertIn("call ptr @__xcc_aot_phase_mark()", body)
        self.assertIn("call void @__xcc_aot_phase_promote_begin", body)
        self.assertIn(
            'call void @"__xcc_aot_phase_promote:record:16:PreprocessResult"',
            body,
        )
        self.assertIn("call void @__xcc_aot_phase_finish", body)
        self.assertNotIn("@__xcc_aot_phase_capture_defer", body)

    def test_native_source_to_object_uses_root_transaction_region(self) -> None:
        llvm_ir = self._rendered_bootstrap()
        symbol = "define i32 @xcc.cc_driver._aot_compile_source_path_to_object("
        start = llvm_ir.index(symbol)
        end = llvm_ir.index("\n}\n", start)
        body = llvm_ir[start:end]

        self.assertIn("call ptr @__xcc_aot_phase_mark()", body)
        preserve_message = "call i1 @__xcc_aot_phase_promote_to(ptr %phase.error.message"
        preserve_payload = "call void @__xcc_aot_phase_promote_object(ptr %phase.error.payload"
        self.assertIn(preserve_message, body)
        self.assertIn(preserve_payload, body)
        self.assertIn("call void @__xcc_aot_phase_finish", body)
        self.assertLess(
            body.index(preserve_message), body.index("call void @__xcc_aot_phase_finish")
        )
        self.assertLess(
            body.index(preserve_payload), body.index("call void @__xcc_aot_phase_finish")
        )

    def test_native_macro_scanners_join_linear_fragment_lists(self) -> None:
        llvm_ir = self._rendered_bootstrap()
        for symbol in (
            "define i32 @xcc.preprocessor.__init__._Preprocessor._expand_text_no_callback(",
            (
                "define ptr @xcc.preprocessor.__init__._Preprocessor."
                "_handle_pragma_operator_no_callback("
            ),
        ):
            start = llvm_ir.index(symbol)
            end = llvm_ir.index("\n}\n", start)
            body = llvm_ir[start:end]
            self.assertIn("call ptr @__xcc_aot_tuple_append", body)
            self.assertIn("call ptr @__xcc_aot_string_join", body)
            self.assertNotIn("call ptr @__xcc_aot_string_concat2", body)

    def test_aot_v6_bootstrap_llvm_is_llc_parseable(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        llvm_ir = self._rendered_bootstrap()
        self.assertIn("define i32 @main(i32 %argc, ptr %argv)", llvm_ir)
        self.assertIn("xcc.cc_driver._aot_compile_source_path_to_object", llvm_ir)
        self.assertIn("xcc.frontend._aot_compile_source_unchecked", llvm_ir)
        self.assertIn("xcc.codegen._LLVMGen.generate", llvm_ir)
        with TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "bootstrap.ll"
            out.write_text(llvm_ir, encoding="utf-8")
            result = subprocess.run(
                (str(llc), "-filetype=obj", str(out), "-o", str(Path(temp_dir) / "probe.o")),
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_slice_metadata_passes_retain_only_one_full_analysis_per_module(self) -> None:
        module_inputs = aot_slice.collect_slice_inputs(
            (
                ROOT / "src/xcc/parser/__init__.py",
                ROOT / "src/xcc/parser/statements.py",
            )
        )
        source_cache = {
            module.name: module.path.read_text(encoding="utf-8") for module in module_inputs
        }
        parsed_cache = aot_slice._slice_parsed_module_cache(module_inputs, source_cache)

        with patch.object(
            aot_slice,
            "check_subset",
            wraps=aot_slice.check_subset,
        ) as checked:
            summary_cache = aot_slice._slice_module_summary_cache(parsed_cache)
            function_types = aot_slice._slice_method_signature_table(
                module_inputs,
                source_cache,
                parsed_cache=parsed_cache,
                summary_cache=summary_cache,
            )
            module_names = frozenset(source_cache)
            rename_maps = {
                module.name: aot_slice._module_rename_map(
                    module.name,
                    source_cache[module.name],
                    module_names,
                    tree=parsed_cache[module.name].tree,
                )
                for module in module_inputs
            }
            module_function_types = aot_slice._module_function_alias_tables(
                function_types,
                rename_maps,
            )
            class_types, _ = aot_slice._slice_class_tables(
                module_inputs,
                source_cache,
                function_types,
                parsed_cache=parsed_cache,
                summary_cache=summary_cache,
                rename_maps=rename_maps,
                module_function_types=module_function_types,
            )
            analysis_cache = aot_slice._slice_lowering_analysis_cache(
                module_inputs,
                parsed_cache,
                class_types,
                module_function_types,
                summary_cache=summary_cache,
            )

        self.assertEqual(checked.call_count, len(module_inputs))
        self.assertEqual(set(analysis_cache), {module.name for module in module_inputs})

    def test_aot_v5_bootstrap_entry_lowers(self) -> None:
        module = self._lowered_bootstrap()
        functions = {function.name: function for function in module.functions}
        self.assertIn("aot_bootstrap_smoke_main", functions)
        self.assertIn("xcc.options.FrontendOptions.__post_init__", functions)
        self.assertIn("FrontendOptions", {record.name for record in module.records})
        self.assertIn(
            "target='xcc.options.FrontendOptions.__post_init__'",
            repr(functions["aot_bootstrap_smoke_main"].body),
        )

    def test_llvm_api_pointer_array_helpers_are_native_leaves(self) -> None:
        module = aot_slice.lower_core_slice(
            (ROOT / "src/xcc/llvm_api.py",),
            root_targets=(
                "xcc.llvm_api.ptr_array",
                "xcc.llvm_api.zero_ptr_array",
                "xcc.llvm_api.optional_zero_ptr_array",
            ),
        )
        functions = {function.name: function for function in module.functions}
        for name in (
            "xcc.llvm_api.ptr_array",
            "xcc.llvm_api.zero_ptr_array",
            "xcc.llvm_api.optional_zero_ptr_array",
        ):
            with self.subTest(name=name):
                self.assertEqual(functions[name].body, ())
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define ptr @xcc.llvm_api.ptr_array(ptr %values)", llvm_ir)
        self.assertIn("define ptr @xcc.llvm_api.zero_ptr_array(i64 %size)", llvm_ir)
        self.assertIn("define ptr @xcc.llvm_api.optional_zero_ptr_array(i64 %size)", llvm_ir)
        self.assertNotIn("declare ptr @calloc(i64, i64)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_calloc(i64 %len, i64 8)", llvm_ir)
        self.assertNotIn("call ptr @calloc(", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values, i64 %index)", llvm_ir)
        self.assertNotIn(
            "define ptr @xcc.llvm_api.ptr_array(ptr %values) {\nentry:\n  ret ptr null", llvm_ir
        )

    def test_slice_lowers_imported_global_string_container_membership(self) -> None:
        module = aot_slice.lower_core_slice(
            (
                ROOT / "src/xcc/ast.py",
                ROOT / "src/xcc/data_layout.py",
                ROOT / "src/xcc/lexer.py",
                ROOT / "src/xcc/parser/__init__.py",
                ROOT / "src/xcc/parser/expressions.py",
                ROOT / "src/xcc/parser/type_specs.py",
            ),
            root_targets=("xcc.parser.expressions.is_parenthesized_type_name_start",),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("@xcc.parser.expressions.is_parenthesized_type_name_start", llvm_ir)
        self.assertNotIn("@__cmp_In", llvm_ir)


    def test_project_imports_are_renamed_to_qualified_slice_targets(self) -> None:
        source = (
            "from xcc.frontend import _aot_compile_source_unchecked\n"
            "from xcc.codegen import generate_llvm_ir\n"
        )
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
        package_map = aot_slice._module_rename_map(
            "xcc.frontend",
            "from xcc.parser import parse\ndef f() -> int:\n    return 1\n",
            {"xcc.frontend", "xcc.parser.__init__"},
        )
        self.assertEqual(package_map["parse"], "xcc.parser.__init__.parse")
        represented_submodule_map = aot_slice._module_rename_map(
            "xcc.aot.types",
            "from xcc.aot import py_ast as ast\n"
            "def render(node: ast.AST) -> str:\n"
            "    return ast.unparse(node)\n",
            {"xcc.aot.types", "xcc.aot.py_ast"},
        )
        self.assertEqual(represented_submodule_map["ast"], "xcc.aot.py_ast")
        relative_module_map = aot_slice._module_rename_map(
            "xcc.sema.__init__",
            "from . import type_resolution as _type_resolution\n"
            "def f() -> bool:\n"
            "    return _type_resolution.is_record_name('struct X')\n",
            {"xcc.sema.__init__", "xcc.sema.type_resolution"},
        )
        self.assertEqual(relative_module_map["_type_resolution"], "xcc.sema.type_resolution")
        renamed = aot_slice._rename_statement_calls(
            (
                IrReturn(
                    IrCall(
                        "_type_resolution.is_record_name",
                        (),
                        IrBoolType(),
                    )
                ),
            ),
            relative_module_map,
        )
        self.assertEqual(
            renamed,
            (
                IrReturn(
                    IrCall(
                        "xcc.sema.type_resolution.is_record_name",
                        (),
                        IrBoolType(),
                    )
                ),
            ),
        )
        assigned_alias_map = aot_slice._module_rename_map(
            "xcc.preprocessor.__init__",
            "from . import text as _text\n"
            "_parse_directive = _text._parse_directive\n"
            "def f() -> int:\n"
            "    return 1\n",
            {"xcc.preprocessor.__init__", "xcc.preprocessor.text"},
        )
        self.assertEqual(
            assigned_alias_map["_parse_directive"],
            "xcc.preprocessor.text._parse_directive",
        )
        records_analysis = analyze_path(ROOT / "src/xcc/sema/records.py")
        function_types = {
            "xcc.sema.records.record_type_name": records_analysis.types.functions[
                "record_type_name"
            ]
        }
        text_analysis = analyze_path(ROOT / "src/xcc/preprocessor/text.py")
        function_types["xcc.preprocessor.text._parse_directive"] = text_analysis.types.functions[
            "_parse_directive"
        ]
        aliased_types = aot_slice._function_types_with_module_aliases(
            function_types,
            {
                "record_type_name": "xcc.sema.records.record_type_name",
                "_parse_directive": "xcc.preprocessor.text._parse_directive",
            },
        )
        self.assertEqual(aliased_types["record_type_name"].return_type.name, "tuple[str, int]")
        self.assertEqual(
            len(aliased_types["_parse_directive"].parameters),
            len(function_types["xcc.preprocessor.text._parse_directive"].parameters),
        )


class AotBootstrapBuildTests(unittest.TestCase):
    def test_build_native_bootstrap_invokes_llc_and_linker(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **kwargs: object) -> object:
            commands.append(tuple(command))

            class Result:
                returncode = 0
                stdout = (
                    "OVERVIEW: llvm system compiler\nUSAGE: llc [options] <input bitcode>\n"
                    if command[1:] == ("--help",)
                    else ""
                )
                stderr = ""

            if command[1:] == ("--help",):
                return Result()
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

        llvm_ir = (
            "define i32 @aot_bootstrap_smoke_main() { ret i32 0 }\n"
            "define void @xcc.options.FrontendOptions.__post_init__() { ret void }\n"
        )
        with (
            TemporaryDirectory() as temp_dir,
            patch("xcc.aot.bootstrap.lower_bootstrap_entry_smoke", return_value=object()),
            patch("xcc.aot.bootstrap.emit_llvm_text", return_value=llvm_ir),
            patch("subprocess.run", fake_run),
        ):
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
                returncode = 0 if command[1:] == ("--help",) else 1
                stdout = (
                    "OVERVIEW: llvm system compiler\nUSAGE: llc [options] <input bitcode>\n"
                    if command[1:] == ("--help",)
                    else ""
                )
                stderr = "" if command[1:] == ("--help",) else "llc failed"

            return Result()

        with (
            TemporaryDirectory() as temp_dir,
            patch("xcc.aot.bootstrap.lower_bootstrap_entry_smoke", return_value=object()),
            patch("xcc.aot.bootstrap.emit_llvm_text", return_value=""),
            patch("subprocess.run", fake_run),
            self.assertRaises(AotError) as ctx,
        ):
            build_native_bootstrap(
                ROOT,
                Path(temp_dir) / "xcc-fail",
                llc="/tool/llc",
                cc="cc",
            )

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0003")
        self.assertEqual(ctx.exception.diagnostics[0].message, "llc failed")


@unittest.skipIf(
    os.environ.get("XCC_SKIP_NATIVE_BOOTSTRAP_TESTS") == "1",
    "native bootstrap behavior matrix runs outside Python coverage",
)
class AotBootstrapNativeBuildTests(unittest.TestCase):
    _native_build_temp: TemporaryDirectory[str] | None = None
    _native_bootstrap_executable: Path | None = None

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._native_build_temp is not None:
            cls._native_build_temp.cleanup()
        super().tearDownClass()

    def _shared_native_bootstrap(self, llc: Path) -> Path:
        cls = type(self)
        if cls._native_bootstrap_executable is None:
            cls._native_build_temp = TemporaryDirectory(prefix="xcc-native-bootstrap-")
            cls._native_bootstrap_executable = build_native_bootstrap(
                ROOT,
                Path(cls._native_build_temp.name) / "xcc",
                llc=str(llc),
                cc="cc",
            )
        return cls._native_bootstrap_executable

    def test_aot_v2_native_bootstrap_fixture_is_shared(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        executable = self._shared_native_bootstrap(llc)

        self.assertIs(self._shared_native_bootstrap(llc), executable)

    def test_real_native_bootstrap_smoke_when_llc_exists(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        output = self._shared_native_bootstrap(llc)
        self.assertTrue(output.exists())
        with TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            source = work / "main.c"
            source.write_text(
                "#define REQUIRED_ALIGNMENT 8 // translation-phase comment\n"
                "typedef struct Object { int kind; } Object;\n"
                "static Object *object_type(Object *value) { return value; }\n"
                "#define OBJECT_CAST(value) ((Object *)(value))\n"
                "#define OBJECT_TYPE(value) object_type(OBJECT_CAST(value))\n"
                "Object *nested(Object *value) {\n"
                "    return OBJECT_TYPE(OBJECT_CAST(value));\n"
                "}\n"
                "static Object *OBJECT_FUNCTION(Object *value) { return value; }\n"
                "#define OBJECT_FUNCTION(value) OBJECT_FUNCTION(OBJECT_CAST(value))\n"
                "static void OBJECT_DECREF(Object *value) { (void)value; }\n"
                "#define OBJECT_DECREF(value) OBJECT_DECREF(OBJECT_CAST(value))\n"
                "void nested_rescan(Object *value) {\n"
                "    OBJECT_DECREF(OBJECT_FUNCTION(value));\n"
                "}\n"
                "void *aligned(void *value) {\n"
                "    void *result = __builtin_assume_aligned(value, REQUIRED_ALIGNMENT);\n"
                "    return result;\n"
                "}\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )
            obj = work / "main.o"
            compile_result = subprocess.run(
                (str(output), "-c", str(source), "-o", str(obj)),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            self.assertTrue(obj.exists())

            if (
                Path("/usr/bin/dwarfdump").is_file()
                and Path("/opt/homebrew/opt/llvm/bin/llvm-dwarfdump").is_file()
            ):
                debug_obj = work / "main-debug.o"
                debug_compile = subprocess.run(
                    (str(output), "-g", "-c", str(source), "-o", str(debug_obj)),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(debug_compile.returncode, 0, debug_compile.stderr)
                dwarf = subprocess.run(
                    ("/usr/bin/dwarfdump", "--debug-info", "--debug-line", str(debug_obj)),
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                unwind = subprocess.run(
                    (
                        "/opt/homebrew/opt/llvm/bin/llvm-dwarfdump",
                        "--eh-frame",
                        str(debug_obj),
                    ),
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                self.assertIn("DW_TAG_compile_unit", dwarf)
                self.assertIn("DW_TAG_subprogram", dwarf)
                self.assertIn("main.c", dwarf)
                self.assertRegex(dwarf, r"0x[0-9a-f]+\s+7\s+[1-9]\s+1")
                self.assertIn("FDE", unwind)

            exe = work / "main"
            link_result = subprocess.run(
                (str(output), str(source), "-o", str(exe)),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(link_result.returncode, 0, link_result.stderr)
            run_result = subprocess.run((str(exe),), check=False)
            self.assertEqual(run_result.returncode, 0)

    def test_real_native_bootstrap_accepts_build_flags(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "build_flags.c"
            obj = root / "build_flags.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            result = subprocess.run(
                (str(executable), "-c", "-O3", "-Wall", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

            unknown_obj = root / "unknown.o"
            unknown = subprocess.run(
                (
                    str(executable),
                    "-c",
                    "-funknown-xcc-option",
                    str(source),
                    "-o",
                    str(unknown_obj),
                ),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(unknown.returncode, 1, unknown.stdout + unknown.stderr)
            self.assertFalse(unknown_obj.exists())

    def test_real_native_bootstrap_preserves_object_macro_replacement(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "object_macro.c"
            obj = root / "object_macro.o"
            source.write_text(
                "#define NATIVE_RECORD struct native_record\n"
                "NATIVE_RECORD { int value; };\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_recursively_expands_object_macro_alias(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "object_macro_alias.c"
            obj = root / "object_macro_alias.o"
            source.write_text(
                "#define NATIVE_RECORD struct native_record\n"
                "#define NATIVE_RECORD_ALIAS NATIVE_RECORD\n"
                "NATIVE_RECORD_ALIAS { int value; };\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_skips_object_macros_in_comments_and_literals(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "macro_regions.c"
            obj = root / "macro_regions.o"
            source.write_text(
                "#define SIGNAL 4 /* signal value */\n"
                "/* Codes for SIGNAL */\n"
                'const char *name = "SIGNAL"; // SIGNAL\n'
                "int signal = SIGNAL;\n"
                "int main(void){return signal == 4 ? 0 : 1;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_evaluates_integer_macro_conditions(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "integer_condition.c"
            obj = root / "integer_condition.o"
            source.write_text(
                "#define LITTLE 1234 /* least-significant first */\n"
                "#define BIG 4321 /* most-significant first */\n"
                "#define ORDER LITTLE\n"
                "#if defined(ORDER) && ORDER == LITTLE\n"
                "struct Box { int value; };\n"
                "#elif ORDER == BIG\n"
                "int broken = ;\n"
                "#else\n"
                "int also_broken = ;\n"
                "#endif\n"
                "int main(void){struct Box box = {0}; return box.value;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_evaluates_has_include_conditions(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            (root / "present.h").write_text("#define PRESENT 7\n", encoding="utf-8")
            source = root / "has_include.c"
            obj = root / "has_include.o"
            source.write_text(
                "#ifndef __has_include\n"
                "#define __has_include(header) 0\n"
                "#endif\n"
                '#if __has_include("present.h")\n'
                '#include "present.h"\n'
                "#else\n"
                "int broken = ;\n"
                "#endif\n"
                '#if __has_include("missing.h")\n'
                "int also_broken = ;\n"
                "#endif\n"
                "int main(void){return PRESENT == 7 ? 0 : 1;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj), "-I", str(root)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_removes_undefined_macro(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "undef.c"
            obj = root / "undef.o"
            source.write_text(
                "#define STALE 1\n"
                "#undef STALE\n"
                "#ifdef STALE\n"
                "int broken = ;\n"
                "#else\n"
                "int active;\n"
                "#endif\n"
                "int main(void){return active;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_parses_nested_compound_if(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "nested_compound.c"
            obj = root / "nested_compound.o"
            source.write_text(
                "int choose(int active) {\n"
                "    if (active) {\n"
                "        return 2;\n"
                "    } else {\n"
                "        return 1;\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_accepts_compatible_pointer_typedefs(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "compatible_typedef.c"
            obj = root / "compatible_typedef.o"
            source.write_text(
                "typedef void *Pointer;\ntypedef void *Pointer;\nint main(void) { return 0; }\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_expands_variadic_function_macro(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "function_macro.c"
            obj = root / "function_macro.o"
            source.write_text(
                "#define ___POSIX_C_DEPRECATED_STARTING_200112L\n"
                "#define DEPRECATED(ver) ___POSIX_C_DEPRECATED_STARTING_##ver\n"
                "#define WRAP(name, type, ...) "
                "enum { __VA_ARGS__ }; typedef type name##_t\n"
                "int old(void) DEPRECATED(200112L);\n"
                "WRAP(qos_class, unsigned int,\n"
                "    QOS_USER = 1,\n"
                "    QOS_DEFAULT = 2,\n"
                ");\n"
                "int main(void) {\n"
                "    qos_class_t value;\n"
                "    return 0;\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_consumes_pragma_operator(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "pragma_operator.c"
            obj = root / "pragma_operator.o"
            source.write_text(
                "#define DO_PRAGMA(value) _Pragma(#value)\n"
                'DO_PRAGMA(clang diagnostic ignored "-Wdeprecated")\n'
                "int value(void) { return 0; }\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_accepts_gnu_signed_keyword_aliases(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "signed_alias.c"
            obj = root / "signed_alias.o"
            source.write_text(
                "typedef __signed char signed_char;\n"
                "int value(void) {\n"
                "    __signed__ int number = (__signed)sizeof(signed_char);\n"
                "    return number;\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_expands_stddef_offsetof(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "stddef_offsetof.c"
            program = root / "stddef_offsetof"
            source.write_text(
                "#include <stddef.h>\n"
                "typedef struct { char x; long y; } aligned_long;\n"
                "int main(void) {\n"
                "    return offsetof(aligned_long, y) == 8 ? 0 : 1;\n"
                "}\n",
                encoding="utf-8",
            )

            compile_result = subprocess.run(
                (str(executable), str(source), "-o", str(program)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                (str(program),),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)

    def test_real_native_bootstrap_expands_limits_macros(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "limits.c"
            obj = root / "limits.o"
            source.write_text(
                "#include <limits.h>\n"
                "#if UCHAR_MAX != 255 || CHAR_BIT != 8\n"
                '#error "invalid char limits"\n'
                "#endif\n"
                "#if SHRT_MAX != 32767 || INT_MAX != 2147483647\n"
                '#error "invalid integer limits"\n'
                "#endif\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_expands_atomic_memory_orders(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "atomic_orders.c"
            obj = root / "atomic_orders.o"
            source.write_text(
                "enum memory_order {\n"
                "    relaxed = __ATOMIC_RELAXED,\n"
                "    consume = __ATOMIC_CONSUME,\n"
                "    acquire = __ATOMIC_ACQUIRE,\n"
                "    release = __ATOMIC_RELEASE,\n"
                "    acq_rel = __ATOMIC_ACQ_REL,\n"
                "    seq_cst = __ATOMIC_SEQ_CST\n"
                "};\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_expands_floating_minima(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "floating_minima.c"
            obj = root / "floating_minima.o"
            source.write_text(
                "#include <math.h>\n"
                "float minimum_float = __FLT_MIN__;\n"
                "double minimum_double = __DBL_MIN__;\n"
                "long double minimum_long_double = __LDBL_MIN__;\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_analyzes_enum_constant_value(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "enum_constant.c"
            obj = root / "enum_constant.o"
            source.write_text(
                "enum unicode_kind { one_byte = 1, two_byte = 2 };\n"
                "static int check(int kind){return kind == one_byte;}\n"
                "int main(void){return check(two_byte);}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_emits_switch_default(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "switch_default.c"
            obj = root / "switch_default.o"
            source.write_text(
                "int choose(int value) {\n"
                "    switch (value) {\n"
                "    case 1:\n"
                "        return 1;\n"
                "    default:\n"
                "        return 0;\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_emits_inferred_global_array(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "inferred_global_array.c"
            program = root / "inferred_global_array"
            source.write_text(
                "static double values[] = {9.090423496703681e+223, 0.0};\n"
                "int main(void) { return values[0] > 0.0 ? 0 : 1; }\n",
                encoding="utf-8",
            )

            compile_result = subprocess.run(
                (str(executable), str(source), "-o", str(program)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                (str(program),),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)

    def test_real_native_bootstrap_embeds_binary_file(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            (root / "data.bin").write_bytes(b"\x00\xff\x2a")
            source = root / "embed.c"
            program = root / "embed"
            source.write_text(
                "unsigned char data[] = {\n"
                '#embed "data.bin"\n'
                "};\n"
                "int main(void) { return data[0] || data[1] != 255 || data[2] != 42; }\n",
                encoding="utf-8",
            )

            compile_result = subprocess.run(
                (str(executable), str(source), "-o", str(program)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                (str(program),),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)

    def test_real_native_bootstrap_accepts_function_pointer_argument(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "function_pointer.c"
            obj = root / "function_pointer.o"
            source.write_text(
                "typedef unsigned long thread_t;\n"
                "int create(thread_t *, const void *, void *(*)(void *), void *);\n"
                "void *routine(void *arg) { return arg; }\n"
                "int start(void) {\n"
                "    thread_t thread;\n"
                "    return create(&thread, 0, routine, 0);\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(obj.exists())

    def test_real_native_bootstrap_links_configure_style_object_when_llc_exists(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "conftest.c"
            obj = root / "conftest.o"
            exe = root / "conftest"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            compile_result = subprocess.run(
                (str(executable), "-c", "-I.", "-DNAME=1", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            self.assertTrue(obj.exists())
            link_result = subprocess.run(
                (str(executable), str(obj), "-o", str(exe)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(link_result.returncode, 0, link_result.stderr)
            self.assertTrue(exe.exists())

    def test_v367_native_bootstrap_missing_include_exits_nonzero(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            source = root / "missing_include.c"
            obj = root / "missing_include.o"
            source.write_text(
                "#include <xcc_v367_missing_header.h>\nint main(void){return 0;}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Include not found", result.stdout + result.stderr)
            self.assertFalse(obj.exists())

    def test_v368_native_bootstrap_include_next_uses_following_system_root(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            include_next_source = root / "include_next.c"
            include_next_obj = root / "include_next.o"
            include_next_source.write_text(
                "#include <inttypes.h>\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            include_next_result = subprocess.run(
                (
                    str(executable),
                    "-c",
                    str(include_next_source),
                    "-o",
                    str(include_next_obj),
                ),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                include_next_result.returncode,
                0,
                include_next_result.stdout + include_next_result.stderr,
            )
            self.assertNotIn(
                "Circular include detected",
                include_next_result.stdout + include_next_result.stderr,
            )
            self.assertTrue(include_next_obj.exists())

    def test_real_native_bootstrap_handles_conditional_include_and_union_when_llc_exists(
        self,
    ) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._shared_native_bootstrap(llc)
            header = root / "guarded.h"
            source = root / "main.c"
            obj = root / "main.o"
            header.write_text(
                "#ifndef GUARDED_H\n"
                "#define GUARDED_H\n"
                '#include "guarded.h" /* self */\n'
                "int guarded;\n"
                "#else\n"
                "int bad;\n"
                "#endif\n",
                encoding="utf-8",
            )
            source.write_text(
                '#include "guarded.h"\n'
                "__PTRDIFF_TYPE__ native_ptrdiff;\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )
            compile_result = subprocess.run(
                (str(executable), "-c", str(source), "-o", str(obj), "-I", str(root)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            self.assertEqual(compile_result.stdout, "")
            self.assertTrue(obj.exists())

            union_source = root / "union.c"
            union_obj = root / "union.o"
            union_exe = root / "union"
            union_source.write_text(
                "union U {\n"
                "  long long whole;\n"
                "  struct { unsigned low; unsigned short middle; unsigned short high; };\n"
                "};\n"
                "union U value = { 0x00050000c0000000LL };\n"
                "int main(void) {\n"
                "  return value.whole == 0x00050000c0000000LL &&\n"
                "         value.low == 0xc0000000U && value.high == 5 ? 0 : 1;\n"
                "}\n",
                encoding="utf-8",
            )
            union_result = subprocess.run(
                (str(executable), "-c", str(union_source), "-o", str(union_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(union_result.returncode, 0, union_result.stdout + union_result.stderr)
            self.assertEqual(union_result.stdout.strip(), "")
            self.assertTrue(union_obj.exists())
            union_link = subprocess.run(
                ("cc", str(union_obj), "-o", str(union_exe)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(union_link.returncode, 0, union_link.stdout + union_link.stderr)
            union_run = subprocess.run(
                (str(union_exe),),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(union_run.returncode, 0, union_run.stdout + union_run.stderr)

            macro_source = root / "multiline_macro_alias.c"
            macro_exe = root / "multiline_macro_alias"
            macro_source.write_text(
                "#define ADD(left, right) ((left) + (right))\n"
                "#define ADD_ALIAS ADD\n"
                "int main(void) {\n"
                "  return ADD_ALIAS(\n"
                "    19,\n"
                "    23) == 42 ? 0 : 1;\n"
                "}\n",
                encoding="utf-8",
            )
            macro_build = subprocess.run(
                (str(executable), str(macro_source), "-o", str(macro_exe)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                macro_build.returncode,
                0,
                macro_build.stdout + macro_build.stderr,
            )
            macro_run = subprocess.run(
                (str(macro_exe),),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(macro_run.returncode, 0, macro_run.stdout + macro_run.stderr)

            selector_source = root / "selector_rescan.c"
            selector_exe = root / "selector_rescan"
            selector_source.write_text(
                "#define PICK(_1, _2, NAME, ...) NAME\n"
                "#define NAMED(type, name) type name; enum\n"
                "#define ANON(type) enum\n"
                "#define ENUM(...) PICK(__VA_ARGS__, NAMED, ANON, )(__VA_ARGS__)\n"
                "typedef ENUM(int, Answer) { ANSWER = 42 };\n"
                "int main(void) { Answer value = ANSWER; return value == 42 ? 0 : 1; }\n",
                encoding="utf-8",
            )
            selector_build = subprocess.run(
                (str(executable), str(selector_source), "-o", str(selector_exe)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                selector_build.returncode,
                0,
                selector_build.stdout + selector_build.stderr,
            )
            selector_run = subprocess.run(
                (str(selector_exe),),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                selector_run.returncode,
                0,
                selector_run.stdout + selector_run.stderr,
            )

            decay_source = root / "array_parameter_decay.c"
            decay_obj = root / "array_parameter_decay.o"
            decay_source.write_text(
                "typedef int Callback(int *values);\n"
                "void accept(Callback *callback);\n"
                "static int callback(int values[]) { return values[0]; }\n"
                "void register_callback(void) { accept(callback); }\n",
                encoding="utf-8",
            )
            decay_result = subprocess.run(
                (str(executable), "-c", str(decay_source), "-o", str(decay_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                decay_result.returncode,
                0,
                decay_result.stdout + decay_result.stderr,
            )
            self.assertTrue(decay_obj.exists())

            typedef_source = root / "typedef.c"
            typedef_obj = root / "typedef.o"
            typedef_source.write_text(
                "typedef struct { int x; } __mbstate_t;\n"
                "__mbstate_t value;\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )
            typedef_result = subprocess.run(
                (str(executable), "-c", str(typedef_source), "-o", str(typedef_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                typedef_result.returncode,
                0,
                typedef_result.stdout + typedef_result.stderr,
            )
            self.assertEqual(typedef_result.stdout.strip(), "")
            self.assertTrue(typedef_obj.exists())

            fnptr_source = root / "fnptr.c"
            fnptr_obj = root / "fnptr.o"
            fnptr_source.write_text(
                "int (*fn)(void *);\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            fnptr_result = subprocess.run(
                (str(executable), "-c", str(fnptr_source), "-o", str(fnptr_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                fnptr_result.returncode,
                0,
                fnptr_result.stdout + fnptr_result.stderr,
            )
            self.assertEqual(fnptr_result.stdout.strip(), "")
            self.assertTrue(fnptr_obj.exists())

            record_source = root / "record_void_ptr.c"
            record_obj = root / "record_void_ptr.o"
            record_source.write_text(
                "struct S { void *cookie; int (*close)(void *); };\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            record_result = subprocess.run(
                (str(executable), "-c", str(record_source), "-o", str(record_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                record_result.returncode,
                0,
                record_result.stdout + record_result.stderr,
            )
            self.assertEqual(record_result.stdout.strip(), "")
            self.assertTrue(record_obj.exists())

            fnparam_source = root / "fnparam.c"
            fnparam_obj = root / "fnparam.o"
            fnparam_source.write_text(
                "int funopen(int (*)(void *, char *, int));\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            fnparam_result = subprocess.run(
                (str(executable), "-c", str(fnparam_source), "-o", str(fnparam_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                fnparam_result.returncode,
                0,
                fnparam_result.stdout + fnparam_result.stderr,
            )
            self.assertEqual(fnparam_result.stdout.strip(), "")
            self.assertTrue(fnparam_obj.exists())
            fnparam_llvm = fnparam_obj.with_suffix(fnparam_obj.suffix + ".ll")
            self.assertIn(
                "declare i32 @funopen(ptr)",
                fnparam_llvm.read_text(encoding="utf-8"),
            )

            proto_pointer_source = root / "proto_pointer.c"
            proto_pointer_obj = root / "proto_pointer.o"
            proto_pointer_source.write_text(
                "void takes(void *p);\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            proto_pointer_result = subprocess.run(
                (str(executable), "-c", str(proto_pointer_source), "-o", str(proto_pointer_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proto_pointer_result.returncode,
                0,
                proto_pointer_result.stdout + proto_pointer_result.stderr,
            )
            self.assertEqual(proto_pointer_result.stdout.strip(), "")
            self.assertTrue(proto_pointer_obj.exists())
            proto_pointer_llvm = proto_pointer_obj.with_suffix(proto_pointer_obj.suffix + ".ll")
            self.assertIn(
                "declare void @takes(ptr)",
                proto_pointer_llvm.read_text(encoding="utf-8"),
            )

            proto_return_source = root / "proto_return.c"
            proto_return_obj = root / "proto_return.o"
            proto_return_source.write_text(
                "int *returns_ptr(void);\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            proto_return_result = subprocess.run(
                (str(executable), "-c", str(proto_return_source), "-o", str(proto_return_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proto_return_result.returncode,
                0,
                proto_return_result.stdout + proto_return_result.stderr,
            )
            self.assertEqual(proto_return_result.stdout.strip(), "")
            self.assertTrue(proto_return_obj.exists())
            proto_return_llvm = proto_return_obj.with_suffix(proto_return_obj.suffix + ".ll")
            self.assertIn(
                "declare ptr @returns_ptr()",
                proto_return_llvm.read_text(encoding="utf-8"),
            )

            binop_source = root / "binop.c"
            binop_obj = root / "binop.o"
            binop_source.write_text(
                "int main(void){return 6 * 3;}\n",
                encoding="utf-8",
            )
            try:
                binop_result = subprocess.run(
                    (str(executable), "-c", str(binop_source), "-o", str(binop_obj)),
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = (
                    exc.stdout.decode("utf-8", "replace")
                    if isinstance(exc.stdout, bytes)
                    else (exc.stdout or "")
                )
                stderr = (
                    exc.stderr.decode("utf-8", "replace")
                    if isinstance(exc.stderr, bytes)
                    else (exc.stderr or "")
                )
                self.fail(stdout + stderr)
            self.assertEqual(
                binop_result.returncode,
                0,
                binop_result.stdout + binop_result.stderr,
            )
            self.assertEqual(binop_result.stdout.strip(), "")
            self.assertTrue(binop_obj.exists())
            binop_llvm = binop_obj.with_suffix(binop_obj.suffix + ".ll")
            self.assertIn(
                "ret i32 18",
                binop_llvm.read_text(encoding="utf-8"),
            )

            pointer_null_source = root / "pointer_null.c"
            pointer_null_obj = root / "pointer_null.o"
            pointer_null_source.write_text(
                "int main(void){int *cursor = 0; return cursor != 0;}\n",
                encoding="utf-8",
            )
            pointer_null_result = subprocess.run(
                (
                    str(executable),
                    "-c",
                    str(pointer_null_source),
                    "-o",
                    str(pointer_null_obj),
                ),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            self.assertEqual(
                pointer_null_result.returncode,
                0,
                pointer_null_result.stdout + pointer_null_result.stderr,
            )
            self.assertEqual(pointer_null_result.stdout.strip(), "")
            self.assertTrue(pointer_null_obj.exists())
            pointer_null_llvm = pointer_null_obj.with_suffix(pointer_null_obj.suffix + ".ll")
            pointer_null_text = pointer_null_llvm.read_text(encoding="utf-8")
            self.assertIn("icmp ne ptr", pointer_null_text)
            self.assertNotIn("inttoptr", pointer_null_text)

            opaque_record_source = root / "opaque_record.c"
            opaque_record_obj = root / "opaque_record.o"
            opaque_record_source.write_text(
                "struct O;\n"
                "int accepts_opaque(struct O *p);\n"
                "struct O *returns_opaque(void);\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )
            opaque_record_result = subprocess.run(
                (str(executable), "-c", str(opaque_record_source), "-o", str(opaque_record_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                opaque_record_result.returncode,
                0,
                opaque_record_result.stdout + opaque_record_result.stderr,
            )
            self.assertEqual(opaque_record_result.stdout.strip(), "")
            self.assertTrue(opaque_record_obj.exists())
            opaque_record_llvm = opaque_record_obj.with_suffix(opaque_record_obj.suffix + ".ll")
            opaque_record_text = opaque_record_llvm.read_text(encoding="utf-8")
            self.assertIn("declare i32 @accepts_opaque(ptr)", opaque_record_text)
            self.assertIn("declare ptr @returns_opaque()", opaque_record_text)

            defined_record_source = root / "defined_record.c"
            defined_record_obj = root / "defined_record.o"
            defined_record_source.write_text(
                "struct D { int x; };\n"
                "int accepts_defined(struct D value);\n"
                "int main(void){return 0;}\n",
                encoding="utf-8",
            )
            defined_record_result = subprocess.run(
                (str(executable), "-c", str(defined_record_source), "-o", str(defined_record_obj)),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                defined_record_result.returncode,
                0,
                defined_record_result.stdout + defined_record_result.stderr,
            )
            self.assertEqual(defined_record_result.stdout.strip(), "")
            self.assertTrue(defined_record_obj.exists())


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
