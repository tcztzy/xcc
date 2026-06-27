import ast
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

    def test_codegen_base_type_lowers_without_callable_dict_dispatch(self) -> None:
        class_types = {}
        for module_path in (ROOT / "src/xcc/codegen.py", ROOT / "src/xcc/types.py"):
            class_types.update(analyze_path(module_path).types.classes)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._base_type"},
            extra_classes=class_types,
        )
        self.assertEqual([function.name for function in module.functions], ["_LLVMGen._base_type"])
        self.assertNotIn("Dict", repr(module.functions[0].body))

    def test_codegen_string_array_element_width_lowers_without_dict_literal(self) -> None:
        class_types = {}
        function_types = {}
        for module_path in (ROOT / "src/xcc/codegen.py", ROOT / "src/xcc/types.py"):
            analysis = analyze_path(module_path)
            class_types.update(analysis.types.classes)
            function_types.update(analysis.types.functions)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._string_array_element_width"},
            extra_classes=class_types,
            extra_functions=function_types,
        )
        self.assertEqual(
            [function.name for function in module.functions],
            ["_LLVMGen._string_array_element_width"],
        )
        self.assertNotIn("Dict", repr(module.functions[0].body))

    def test_codegen_decode_string_lowers_without_escape_dict_literal(self) -> None:
        class_types = analyze_path(ROOT / "src/xcc/codegen.py").types.classes
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._decode_string"},
            extra_classes=class_types,
        )
        self.assertEqual([function.name for function in module.functions], ["_LLVMGen._decode_string"])
        self.assertNotIn("Dict", repr(module.functions[0].body))

    def test_codegen_encode_string_units_lowers_with_typed_units_list(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._encode_string_units"},
        )
        self.assertEqual(
            [function.name for function in module.functions],
            ["_LLVMGen._encode_string_units"],
        )
        self.assertIn("IrTupleType(elements=(IrIntType", repr(module.functions[0].body))

    def test_codegen_member_path_lowers_without_starred_list_literal(self) -> None:
        class_types = {}
        for module_path in (
            ROOT / "src/xcc/codegen.py",
            ROOT / "src/xcc/sema/symbols.py",
            ROOT / "src/xcc/types.py",
        ):
            class_types.update(analyze_path(module_path).types.classes)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._member_path"},
            extra_classes=class_types,
        )
        self.assertEqual([function.name for function in module.functions], ["_LLVMGen._member_path"])
        self.assertNotIn("Starred", repr(module.functions[0].body))

    def test_codegen_walk_allocas_lowers_typed_optional_symbol_lookup(self) -> None:
        class_types = {}
        function_types = {}
        for module_path in (
            ROOT / "src/xcc/ast.py",
            ROOT / "src/xcc/codegen.py",
            ROOT / "src/xcc/sema/symbols.py",
            ROOT / "src/xcc/types.py",
        ):
            analysis = analyze_path(module_path)
            class_types.update(analysis.types.classes)
            function_types.update(analysis.types.functions)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._walk_allocas"},
            extra_classes=class_types,
            extra_functions=function_types,
        )
        self.assertEqual([function.name for function in module.functions], ["_LLVMGen._walk_allocas"])
        self.assertIn("IrRecordType(name='VarSymbol')", repr(module.functions[0].body))

    def test_codegen_atomic_builtin_call_lowers_without_opcode_dicts(self) -> None:
        class_types = {}
        function_types = {}
        for module_path in (
            ROOT / "src/xcc/ast.py",
            ROOT / "src/xcc/codegen.py",
            ROOT / "src/xcc/sema/symbols.py",
            ROOT / "src/xcc/types.py",
        ):
            analysis = analyze_path(module_path)
            class_types.update(analysis.types.classes)
            function_types.update(analysis.types.functions)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._atomic_builtin_call"},
            extra_classes=class_types,
            extra_functions=function_types,
        )
        self.assertEqual(
            [function.name for function in module.functions],
            ["_LLVMGen._atomic_builtin_call"],
        )
        self.assertNotIn("Dict", repr(module.functions[0].body))

    def test_codegen_atomic_rmw_new_value_lowers_without_unary_all_ones(self) -> None:
        class_types = analyze_path(ROOT / "src/xcc/codegen.py").types.classes
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._atomic_rmw_new_value"},
            extra_classes=class_types,
        )
        self.assertEqual(
            [function.name for function in module.functions],
            ["_LLVMGen._atomic_rmw_new_value"],
        )
        self.assertNotIn("UnaryOp", repr(module.functions[0].body))

    def test_codegen_assign_lowers_without_compound_operator_dicts(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        assign_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_assign"
        ]
        self.assertEqual(len(assign_methods), 1)
        self.assertFalse(
            any(isinstance(node, ast.Dict) for node in ast.walk(assign_methods[0])),
            "_LLVMGen._assign should not use dict literal operator dispatch",
        )

    def test_codegen_binary_lowers_without_operator_dicts(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        binary_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_binary"
        ]
        self.assertEqual(len(binary_methods), 1)
        self.assertFalse(
            any(isinstance(node, ast.Dict) for node in ast.walk(binary_methods[0])),
            "_LLVMGen._binary should not use dict literal operator dispatch",
        )

    def test_codegen_float_rank_lowers_without_rank_dict(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        rank_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_float_rank"
        ]
        self.assertEqual(len(rank_methods), 1)
        self.assertFalse(
            any(isinstance(node, ast.Dict) for node in ast.walk(rank_methods[0])),
            "_LLVMGen._float_rank should not use dict literal rank dispatch",
        )

    def test_codegen_compare_lowers_without_predicate_dicts(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        compare_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_compare"
        ]
        self.assertEqual(len(compare_methods), 1)
        self.assertFalse(
            any(isinstance(node, ast.Dict) for node in ast.walk(compare_methods[0])),
            "_LLVMGen._compare should not use dict literal predicate dispatch",
        )

    def test_codegen_unary_lowers_without_negative_constint_literals(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        unary_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_unary"
        ]
        self.assertEqual(len(unary_methods), 1)
        self.assertFalse(
            any(isinstance(node, ast.UnaryOp) for node in ast.walk(unary_methods[0])),
            "_LLVMGen._unary should not use Python unary literals in LLVM API args",
        )

    def test_codegen_function_designator_lowers_without_setdefault(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function_designator_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_function_designator"
        ]
        self.assertEqual(len(function_designator_methods), 1)
        self.assertNotIn("setdefault", ast.unparse(function_designator_methods[0]))

    def test_codegen_const_from_bytes_lowers_without_any_call(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        const_from_bytes_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_const_from_bytes"
        ]
        self.assertEqual(len(const_from_bytes_methods), 1)
        self.assertNotIn("any(", ast.unparse(const_from_bytes_methods[0]))
        self.assertNotIn("int.from_bytes", ast.unparse(const_from_bytes_methods[0]))

    def test_codegen_const_value_bytes_lowers_with_typed_integer_locals(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        const_value_bytes_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_const_value_bytes"
        ]
        self.assertEqual(len(const_value_bytes_methods), 1)
        annotated_names = {
            node.target.id
            for node in ast.walk(const_value_bytes_methods[0])
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertIn("raw", annotated_names)
        self.assertIn("mask", annotated_names)
        self.assertIn("masked", annotated_names)

    def test_codegen_const_struct_bytes_lowers_without_mutable_bytearray(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        const_struct_bytes_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_const_struct_bytes"
        ]
        self.assertEqual(len(const_struct_bytes_methods), 1)
        method = const_struct_bytes_methods[0]
        self.assertNotIn("bytearray", ast.unparse(method))
        self.assertFalse(
            any(
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Subscript) for target in node.targets)
                for node in ast.walk(method)
            ),
            "_const_struct_bytes should stay inside the immutable bytes subset",
        )

    def test_codegen_eval_const_expr_lowers_negative_float_without_unary_op(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eval_const_expr_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_eval_const_expr"
        ]
        self.assertEqual(len(eval_const_expr_methods), 1)
        self.assertFalse(
            any(
                isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Name)
                and node.operand.id == "float_value"
                for node in ast.walk(eval_const_expr_methods[0])
            ),
            "_eval_const_expr should express negative float constants as binary subtraction",
        )

    def test_codegen_eval_const_expr_lowers_optional_array_guard_without_boolop(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eval_const_expr_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_eval_const_expr"
        ]
        self.assertEqual(len(eval_const_expr_methods), 1)
        method = eval_const_expr_methods[0]
        method_source = ast.unparse(method)
        self.assertNotIn("value_type is not None and value_type.is_array()", method_source)
        self.assertTrue(
            any(
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "value_type"
                for node in ast.walk(method)
            ),
            "_eval_const_expr should annotate value_type before Optional narrowing",
        )

    def test_codegen_const_identifier_addr_lowers_type_lookup_without_bool_or(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_eval_const_identifier", "_eval_const_addr"}
        ]
        self.assertEqual({method.name for method in methods}, {"_eval_const_identifier", "_eval_const_addr"})
        for method in methods:
            with self.subTest(method=method.name):
                method_source = ast.unparse(method)
                self.assertNotIn("or self._lookup_symbol_type", method_source)
                self.assertTrue(
                    any(
                        isinstance(node, ast.AnnAssign)
                        and isinstance(node.target, ast.Name)
                        and node.target.id == "value_type"
                        for node in ast.walk(method)
                    ),
                    f"{method.name} should annotate value_type before Optional narrowing",
                )

    def test_codegen_eval_record_init_lowers_without_nested_function(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eval_record_init_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_eval_record_init"
        ]
        self.assertEqual(len(eval_record_init_methods), 1)
        nested_functions = [
            node
            for node in ast.walk(eval_record_init_methods[0])
            if isinstance(node, ast.FunctionDef) and node.name != "_eval_record_init"
        ]
        self.assertEqual(nested_functions, [])
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Subscript)
                for node in ast.walk(eval_record_init_methods[0])
            ),
            "_eval_record_init should append through typed local list variables",
        )

    def test_codegen_eval_record_path_init_lowers_typed_path_unpack(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eval_record_path_init_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_eval_record_path_init"
        ]
        self.assertEqual(len(eval_record_path_init_methods), 1)
        method = eval_record_path_init_methods[0]
        self.assertFalse(
            any(
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Tuple) for target in node.targets)
                and isinstance(node.value, ast.Subscript)
                and ast.unparse(node.value) == "path[0]"
                for node in ast.walk(method)
            ),
            "_eval_record_path_init should unpack path entries through typed locals",
        )
        annotated_names = {
            node.target.id
            for node in ast.walk(method)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertIn("record_name", annotated_names)
        self.assertIn("field_index", annotated_names)
        self.assertIn("member", annotated_names)

    def test_codegen_llvmgen_lowers_without_dead_term_flag(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        self.assertNotIn("self._term", source)

    def test_codegen_emit_return_lowers_func_sym_return_type_without_ifexp(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        emit_return_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_emit_return"
        ]
        self.assertEqual(len(emit_return_methods), 1)
        method_source = ast.unparse(emit_return_methods[0])
        self.assertNotIn("if self._func_sym else", method_source)
        self.assertTrue(
            any(
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "return_type"
                for node in ast.walk(emit_return_methods[0])
            ),
            "_emit_return should use a typed local for optional function return type",
        )

    def test_codegen_emit_globals_lowers_without_starred_fallback_list(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        emit_globals_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_emit_globals"
        ]
        self.assertEqual(len(emit_globals_methods), 1)
        method = emit_globals_methods[0]
        self.assertFalse(any(isinstance(node, ast.Starred) for node in ast.walk(method)))
        annotated_names = {
            node.target.id
            for node in ast.walk(method)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertIn("externals", annotated_names)

    def test_codegen_struct_type_overrides_lowers_dict_get_without_default(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_struct_type_with_member_overrides"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertNotIn("member_type_overrides.get(index, member.type_)", method_source)
        annotated_names = {
            node.target.id
            for node in ast.walk(methods[0])
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertIn("member_type", annotated_names)

    def test_codegen_flexible_array_overrides_lowers_typed_last_index(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_flexible_array_member_overrides"
        ]
        self.assertEqual(len(methods), 1)
        annotated_names = {
            node.target.id
            for node in ast.walk(methods[0])
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertIn("last_index", annotated_names)
        self.assertIn("result", annotated_names)
        self.assertFalse(
            any(isinstance(node, ast.Dict) and node.keys for node in ast.walk(methods[0])),
            "_flexible_array_member_overrides should build non-empty dicts by assignment",
        )

    def test_codegen_identifier_lowers_without_fstring_literal(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        identifier_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_identifier"
        ]
        self.assertEqual(len(identifier_methods), 1)
        self.assertFalse(
            any(isinstance(node, ast.JoinedStr) for node in ast.walk(identifier_methods[0])),
            "_LLVMGen._identifier should not build __func__ string literals with f-strings",
        )
        self.assertNotIn(
            "name == '__func__' and",
            ast.unparse(identifier_methods[0]),
        )
        self.assertNotIn("self._func_sym and", ast.unparse(identifier_methods[0]))

    def test_type_helpers_usual_arithmetic_conversion_lowers_global_type_name_checks(
        self,
    ) -> None:
        class_types = analyze_path(ROOT / "src/xcc/types.py").types.classes
        source = (ROOT / "src/xcc/sema/type_helpers.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/sema/type_helpers.py"),
            include_records=frozenset(),
            include_functions={"usual_arithmetic_conversion"},
            extra_classes=class_types,
        )
        self.assertEqual([function.name for function in module.functions], ["usual_arithmetic_conversion"])
        self.assertNotIn("LONGDOUBLE.name", repr(module.functions[0].body))
        self.assertNotIn("DOUBLE.name", repr(module.functions[0].body))

    def test_codegen_union_size_lowers_without_generator_max(self) -> None:
        class_types = {}
        for module_path in (
            ROOT / "src/xcc/codegen.py",
            ROOT / "src/xcc/sema/symbols.py",
            ROOT / "src/xcc/types.py",
        ):
            class_types.update(analyze_path(module_path).types.classes)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._type_align", "_LLVMGen._union_size"},
            extra_classes=class_types,
        )
        functions = {function.name: function for function in module.functions}
        self.assertIn("_LLVMGen._type_align", functions)
        self.assertIn("_LLVMGen._union_size", functions)
        self.assertNotIn("GeneratorExp", repr(module.functions))

    def test_codegen_union_storage_member_lowers_without_key_callback(self) -> None:
        class_types = {}
        for module_path in (
            ROOT / "src/xcc/codegen.py",
            ROOT / "src/xcc/sema/symbols.py",
            ROOT / "src/xcc/types.py",
        ):
            class_types.update(analyze_path(module_path).types.classes)
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/codegen.py"),
            include_records=frozenset(),
            include_functions={"_LLVMGen._union_storage_member"},
            extra_classes=class_types,
        )
        self.assertEqual(
            [function.name for function in module.functions],
            ["_LLVMGen._union_storage_member"],
        )
        self.assertNotIn("FunctionDef", repr(module.functions[0].body))

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
