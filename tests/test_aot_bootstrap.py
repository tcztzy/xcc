import ast
import re
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
    IrBoolType,
    IrCall,
    IrReturn,
    lower_bootstrap_entry_smoke,
    lower_source_to_ir,
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
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py"))) - len(
            HOSTED_ONLY_MODULES
        )
        self.assertEqual(len(modules), expected_count)
        self.assertEqual(modules[0].name, "xcc.__init__")
        self.assertIn("xcc.aot.bootstrap", {module.name for module in modules})
        self.assertTrue(HOSTED_ONLY_MODULES.isdisjoint({module.name for module in modules}))
        self.assertEqual(modules[-1].name, "xcc.x86_64_asm")

    def test_rejects_non_repository_root(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_bootstrap_sources(ROOT / "tests")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0001")

    def test_summarizes_bootstrap_admission(self) -> None:
        report = summarize_bootstrap_admission(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py"))) - len(
            HOSTED_ONLY_MODULES
        )
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

    def test_legacy_c_bootstrap_slice_excludes_aot_compiler_modules(self) -> None:
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
                "def marker() -> None:\n"
                "    return None\n",
                encoding="utf-8",
            )

            with self.assertRaises(AotError) as ctx:
                plan_bootstrap_entry(root)

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0002")
        self.assertIn("xcc.cc_driver", ctx.exception.diagnostics[0].message)


class AotBootstrapLoweringTests(unittest.TestCase):
    def test_bootstrap_compiler_path_reaches_frontend_and_codegen(self) -> None:
        module = lower_bootstrap_entry_smoke(ROOT)
        functions = {function.name for function in module.functions}
        self.assertIn("xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked", functions)
        self.assertIn("xcc.frontend._aot_compile_source_unchecked", functions)
        self.assertIn("xcc.codegen.generate_llvm_ir", functions)
        self.assertIn("xcc.codegen._LLVMGen.generate", functions)

    def test_bootstrap_llvm_has_no_conftest_include_fast_path(self) -> None:
        llvm_ir = emit_llvm_text(lower_bootstrap_entry_smoke(ROOT))
        self.assertNotIn("conftest.c", llvm_ir)
        self.assertNotIn("#include <", llvm_ir)
        self.assertNotIn("call ptr @strstr(ptr %source_path", llvm_ir)

    def test_native_preprocessing_uses_one_exact_transaction_region(self) -> None:
        llvm_ir = emit_llvm_text(lower_bootstrap_entry_smoke(ROOT))
        symbol = (
            "define i32 @xcc.preprocessor.__init__.preprocess_source_no_callback("
        )
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

    def test_native_macro_scanners_join_linear_fragment_lists(self) -> None:
        llvm_ir = emit_llvm_text(lower_bootstrap_entry_smoke(ROOT))
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

    def test_bootstrap_real_compiler_path_emits_llc_parseable_llvm(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        module = lower_bootstrap_entry_smoke(ROOT)
        llvm_ir = emit_llvm_text(module)
        out = ROOT / "build/aot/probes/bootstrap-real-path.ll"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(llvm_ir, encoding="utf-8")
        self.assertIn("define i32 @main(i32 %argc, ptr %argv)", llvm_ir)
        self.assertIn("xcc.cc_driver._aot_compile_source_path_to_object", llvm_ir)
        self.assertIn("xcc.frontend._aot_compile_source_unchecked", llvm_ir)
        self.assertIn("xcc.codegen._LLVMGen.generate", llvm_ir)
        with TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                (str(llc), "-filetype=obj", str(out), "-o", str(Path(temp_dir) / "probe.o")),
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rewrites_preprocessor_protocol_calls_to_concrete_preprocessor(self) -> None:
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.__init__.preprocess_source",
                {},
            ),
            "xcc.preprocessor.__init__.preprocess_source_no_callback",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.process._ProcessTextPreprocessor._expand_line",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._expand_line_no_callback",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "_ProcessTextPreprocessor._should_collect_function_macro_continuation",
                {
                    "_ProcessTextPreprocessor._should_collect_function_macro_continuation": (
                        "xcc.preprocessor.process._ProcessTextPreprocessor."
                        "_should_collect_function_macro_continuation"
                    )
                },
            ),
            "xcc.preprocessor.__init__._Preprocessor._should_collect_function_macro_continuation",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.process._ProcessTextPreprocessor._handle_include",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._handle_include",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.process._ProcessTextPreprocessor._record_pragma_once",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._record_pragma_once",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.process._ProcessTextPreprocessor._handle_conditional",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._handle_conditional_no_callback",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.process._ProcessTextPreprocessor."
                "_handle_conditional_for_process",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor."
            "_handle_conditional_for_process_no_callback",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "_ProcessTextPreprocessor._handle_define",
                {
                    "_ProcessTextPreprocessor._handle_define": (
                        "xcc.preprocessor.process._ProcessTextPreprocessor._handle_define"
                    )
                },
            ),
            "xcc.preprocessor.__init__._Preprocessor._handle_define_no_callback",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.process._ProcessTextPreprocessor._handle_undef",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._handle_undef_no_callback",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.__init__._Preprocessor._parse_include_target",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._parse_include_target_no_macro",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.preprocessor.__init__._Preprocessor._skip_guarded_include",
                {},
            ),
            "xcc.preprocessor.__init__._Preprocessor._skip_guarded_include_no_callback",
        )

    def test_rewrites_statement_parser_protocol_calls_to_concrete_parser(self) -> None:
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.parser.statements._StatementParser._parse_statement",
                {},
            ),
            "xcc.parser.__init__.Parser._parse_statement",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "_StatementParser._check_keyword",
                {
                    "_StatementParser._check_keyword": (
                        "xcc.parser.statements._StatementParser._check_keyword"
                    )
                },
            ),
            "xcc.parser.__init__.Parser._check_keyword",
        )

    def test_statement_parser_protocol_calls_use_concrete_native_signature(self) -> None:
        module_inputs = aot_slice.collect_slice_inputs(
            (
                ROOT / "src/xcc/parser/__init__.py",
                ROOT / "src/xcc/parser/statements.py",
            )
        )
        source_cache = {
            module.name: module.path.read_text(encoding="utf-8") for module in module_inputs
        }

        function_types = aot_slice._slice_method_signature_table(module_inputs, source_cache)
        protocol = function_types[
            "xcc.parser.statements._StatementParser._parse_compound_stmt"
        ]
        concrete = function_types["xcc.parser.__init__.Parser._parse_compound_stmt"]

        self.assertEqual(protocol.parameters, concrete.parameters)
        self.assertEqual(protocol.parameter_defaults, concrete.parameter_defaults)
        self.assertEqual(protocol.return_type, concrete.return_type)
        self.assertEqual(protocol.vararg, concrete.vararg)

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

    def test_rewrites_file_scope_analyzer_protocol_calls_to_concrete_analyzer(self) -> None:
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.sema.declarations._FileScopeAnalyzer._register_type_spec",
                {},
            ),
            "xcc.sema.__init__.Analyzer._register_type_spec",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "_FileScopeAnalyzer._resolve_type",
                {
                    "_FileScopeAnalyzer._resolve_type": (
                        "xcc.sema.declarations._FileScopeAnalyzer._resolve_type"
                    )
                },
            ),
            "xcc.sema.__init__.Analyzer._resolve_type",
        )
        self.assertEqual(
            aot_slice._rename_call_target(
                "xcc.sema.declarations._FileScopeAnalyzer."
                "_register_function_typed_file_scope_decl",
                {},
            ),
            "xcc.sema.__init__.Analyzer._register_function_typed_file_scope_decl",
        )

    def test_file_scope_analyzer_protocol_fields_are_cast_to_concrete_analyzer(self) -> None:
        source = (ROOT / "src/xcc/sema/declarations.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "analyze_file_scope_decl"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("a = cast('Analyzer', analyzer)", method_source)
        self.assertNotIn("a = analyzer", method_source)

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
        self.assertIn("target='_aot_compile_source_path_to_object'", body)
        self.assertIn("target='_aot_exec_argv'", body)
        llvm_ir = emit_llvm_text(module)
        self.assertIn(
            "define i32 @_aot_compile_smoke_source_to_object(i32 %argc, ptr %argv)",
            llvm_ir,
        )
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %argv, i64 %", llvm_ir)
        self.assertNotIn("call ptr @__getitem", llvm_ir)

    def test_smoke_compiler_body_accepts_configure_compile_flags(self) -> None:
        source = (ROOT / "src/xcc/cc_driver.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/cc_driver.py"),
            include_records=frozenset(),
            include_functions={"_aot_compile_smoke_source_to_object"},
        )
        body = repr(module.functions[0].body)
        self.assertIn("target='_aot_arg_is_c_source'", body)
        self.assertIn("target='_aot_default_object_path'", body)
        self.assertIn("target='_aot_compile_source_path_to_object'", body)
        self.assertIn("target='_aot_exec_argv'", body)
        self.assertIn("target='__str_startswith'", body)

    def test_native_preprocessor_constructor_uses_no_callback_initializer(self) -> None:
        module = lower_bootstrap_entry_smoke(ROOT)
        functions = {function.name: function for function in module.functions}
        self.assertEqual(
            functions["xcc.preprocessor.__init__._Preprocessor.__init__"].body,
            (),
        )
        self.assertNotEqual(
            functions["xcc.preprocessor.__init__._Preprocessor._init_no_callback"].body,
            (),
        )

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
        self.assertIn(
            "target='xcc.cc_driver._aot_compile_source_path_to_object'",
            repr(smoke_compiler.body),
        )
        self.assertIn("target='xcc.cc_driver._aot_arg_is_c_source'", repr(smoke_compiler.body))
        self.assertIn("target='xcc.cc_driver._aot_is_linker_flag'", repr(smoke_compiler.body))
        self.assertIn("target='xcc.cc_driver._aot_link_argv'", repr(smoke_compiler.body))
        self.assertIn("target='xcc.cc_driver._aot_exec_argv'", repr(smoke_compiler.body))
        self.assertNotIn("target='xcc.cc_driver._aot_is_smoke_source'", repr(smoke_compiler.body))
        self.assertNotIn("target='xcc.cc_driver._aot_smoke_llvm_ir'", repr(smoke_compiler.body))
        self.assertIn("xcc.cc_driver._aot_compile_source_path_to_object", functions)
        self.assertIn("xcc.cc_driver._aot_compile_source_to_llvm_ir", functions)
        self.assertIn("xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked", functions)
        self.assertNotIn("xcc.cc_driver._aot_is_smoke_source", functions)
        self.assertNotIn("xcc.cc_driver._aot_is_autoconf_stdio_run_probe", functions)
        self.assertNotIn("xcc.cc_driver._aot_smoke_llvm_ir", functions)
        self.assertIn("xcc.cc_driver._aot_arg_is_c_source", functions)
        self.assertIn("xcc.cc_driver._aot_default_object_path", functions)
        self.assertIn("xcc.cc_driver._aot_link_object_path", functions)
        self.assertIn("xcc.cc_driver._aot_is_linker_flag", functions)
        self.assertIn("xcc.cc_driver._aot_link_argv", functions)
        self.assertNotIn("xcc.cc_driver._aot_is_smoke_compile_command", functions)
        self.assertIn("xcc.cc_driver._aot_smoke_llvm_path", functions)
        self.assertIn("xcc.cc_driver._aot_smoke_llc_argv", functions)
        self.assertIn("xcc.cc_driver._aot_read_text_file", functions)
        self.assertIn("xcc.cc_driver._aot_write_text_file", functions)
        self.assertIn("xcc.cc_driver._aot_exec_argv", functions)
        self.assertIn("xcc.preprocessor.__init__.preprocess_source_no_callback", functions)
        self.assertEqual(
            functions["xcc.preprocessor.__init__._Preprocessor.__init__"].body,
            (),
        )
        self.assertNotEqual(
            functions["xcc.preprocessor.__init__._Preprocessor._init_no_callback"].body,
            (),
        )
        self.assertIn(
            "xcc.preprocessor.__init__._Preprocessor."
            "_handle_conditional_for_process_no_callback",
            functions,
        )
        self.assertIn(
            "xcc.preprocessor.__init__._Preprocessor._parse_include_target_no_macro",
            functions,
        )
        self.assertIn(
            "xcc.preprocessor.__init__._Preprocessor._parse_header_name_operand_no_macro",
            functions,
        )
        self.assertIn("xcc.preprocessor.__init__._Preprocessor._expand_line_no_callback", functions)
        self.assertIn("xcc.preprocessor.__init__._Preprocessor._expand_macro_text", functions)
        self.assertIn(
            "xcc.preprocessor.__init__._Preprocessor._handle_define_no_callback",
            functions,
        )
        self.assertIn(
            "xcc.preprocessor.__init__._Preprocessor._handle_undef_no_callback",
            functions,
        )
        self.assertIn(
            "xcc.preprocessor.__init__._Preprocessor._skip_guarded_include_no_callback",
            functions,
        )

        llvm_ir = emit_llvm_text(module)

        type_map_set_start = llvm_ir.index(
            "define void @xcc.sema.symbols.TypeMap.set("
        )
        type_map_set_end = llvm_ir.index("\n}\n", type_map_set_start)
        type_map_set_llvm = llvm_ir[type_map_set_start:type_map_set_end]
        self.assertIn("call ptr @__xcc_aot_tuple_append", type_map_set_llvm)
        self.assertNotIn("dictset.cond", type_map_set_llvm)
        type_map_get_start = llvm_ir.index(
            "define ptr @xcc.sema.symbols.TypeMap.get("
        )
        type_map_get_end = llvm_ir.index("\n}\n", type_map_get_start)
        type_map_get_llvm = llvm_ir[type_map_get_start:type_map_get_end]
        self.assertIn("@__xcc_aot_identity_dict_find_index", type_map_get_llvm)
        self.assertIn("label %typemap.get.found", type_map_get_llvm)
        self.assertNotIn("typemap.get.cond", type_map_get_llvm)
        self.assertIn("@__xcc_aot_dict_bump_state", type_map_set_llvm)
        self.assertIn("@__xcc_aot_identity_dict_note_index", type_map_set_llvm)
        typedef_lookup_start = llvm_ir.index(
            "define ptr @xcc.parser.__init__.Parser._lookup_typedef("
        )
        typedef_lookup_end = llvm_ir.index("\n}\n", typedef_lookup_start)
        typedef_lookup_llvm = llvm_ir[typedef_lookup_start:typedef_lookup_end]
        self.assertIn("@__xcc_aot_string_tuple_find_index", typedef_lookup_llvm)
        self.assertNotIn("contains.cond", typedef_lookup_llvm)

        self.assertIn("define i32 @main(i32 %argc, ptr %argv)", llvm_ir)
        self.assertIn(
            "%argv_tuple = call ptr @__xcc_aot_c_argv_to_tuple(i32 %argc, ptr %argv)",
            llvm_ir,
        )
        self.assertIn(
            "call i32 @aot_bootstrap_smoke_main("
            "i32 %argc, ptr %argv_tuple, ptr %result_out, ptr %error_record)",
            llvm_ir,
        )
        self.assertIn("%failed = icmp ne i32 %status, 0", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_c_argv_to_tuple(i32 %argc32, ptr %argv)", llvm_ir)
        self.assertNotIn("__xcc_aot_bootstrap_cc_delegate", llvm_ir)
        self.assertNotIn("@__xcc_aot_cc", llvm_ir)
        self.assertIn(
            "define i32 @xcc.cc_driver._aot_compile_smoke_source_to_object("
            "i32 %argc, ptr %argv, ptr %result_out, ptr %error_out)",
            llvm_ir,
        )
        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %argv)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %argv,", llvm_ir)
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
        self.assertIn("define i1 @xcc.cc_driver._aot_arg_is_c_source(", llvm_ir)
        self.assertIn("define ptr @xcc.cc_driver._aot_default_object_path(", llvm_ir)
        self.assertIn("define ptr @xcc.cc_driver._aot_link_object_path(", llvm_ir)
        self.assertIn("define i1 @xcc.cc_driver._aot_is_linker_flag(", llvm_ir)
        self.assertIn("define ptr @xcc.cc_driver._aot_link_argv(", llvm_ir)
        self.assertIn(
            "define i32 @xcc.cc_driver._aot_compile_source_path_to_object(",
            llvm_ir,
        )
        self.assertIn(
            "call i32 @xcc.cc_driver._aot_compile_source_path_to_object(",
            llvm_ir,
        )
        self.assertIn("call ptr @xcc.cc_driver._aot_link_argv(", llvm_ir)
        self.assertNotIn("%arg1_cmp = call i32 @strcmp", llvm_ir)
        self.assertNotIn("%arg3_cmp = call i32 @strcmp", llvm_ir)
        self.assertIn(
            "define i32 @xcc.cc_driver._aot_compile_source_to_llvm_ir("
            "ptr %source_path, ptr %source_text, ptr %include_dirs, "
            "ptr %defines, ptr %undefs, ptr %std, ptr %result_out, ptr %error_out)",
            llvm_ir,
        )
        self.assertIn(
            "call i32 @xcc.cc_driver._aot_compile_source_to_llvm_ir(",
            llvm_ir,
        )
        self.assertIn(
            "call i32 @xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked(",
            llvm_ir,
        )
        self.assertIn("define ptr @xcc.cc_driver._aot_default_system_include_dirs(", llvm_ir)
        self.assertNotIn("call ptr @strstr(ptr %source_path", llvm_ir)
        self.assertNotIn("call ptr @strstr(ptr %source_text", llvm_ir)
        self.assertNotIn("conftest.c", llvm_ir)
        self.assertNotIn("#include <", llvm_ir)
        self.assertNotIn("define i32 @main()", llvm_ir)
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
        self.assertIn("ret i32 %exec", llvm_ir)
        self.assertIn("call i32 @__xcc_aot_execvp_tuple(ptr %argv)", llvm_ir)
        self.assertNotIn("call i32 @__xcc_aot_execvp_tuple(ptr %llc_argv)", llvm_ir)
        self.assertNotIn("%llc_argv = alloca ptr, i64 6", llvm_ir)
        self.assertNotIn("call i32 @execvp(ptr @.str", llvm_ir)
        self.assertIn("/opt/homebrew/opt/llvm/bin/llc", llvm_ir)
        self.assertIn("declare i32 @fork()", llvm_ir)
        self.assertIn("declare i32 @waitpid(i32, ptr, i32)", llvm_ir)
        self.assertIn("declare void @_exit(i32)", llvm_ir)
        self.assertIn("call i32 @fork()", llvm_ir)
        self.assertIn("call i32 @waitpid(", llvm_ir)
        self.assertIn(
            "@xcc.preprocessor.__init__._Preprocessor._expand_macro_text(",
            llvm_ir,
        )
        self.assertIn(
            "@xcc.preprocessor.__init__._Preprocessor._expand_line_no_callback(",
            llvm_ir,
        )
        self.assertIn(
            "@xcc.preprocessor.__init__._Preprocessor._handle_define_no_callback(",
            llvm_ir,
        )
        self.assertIn(
            "@xcc.preprocessor.__init__._Preprocessor._parse_include_target_no_macro(",
            llvm_ir,
        )
        self.assertIn(
            "@xcc.preprocessor.__init__._Preprocessor._skip_guarded_include_no_callback(",
            llvm_ir,
        )
        parser_symbol = (
            "@xcc.preprocessor.__init__._Preprocessor."
            "_parse_header_name_operand_no_macro("
        )
        parser_match = re.search(
            rf"^define [^\n]+{re.escape(parser_symbol)}",
            llvm_ir,
            re.MULTILINE,
        )
        assert parser_match is not None
        parser_start = parser_match.start()
        parser_end = llvm_ir.index("\ndefine ", parser_start + 1)
        parser_llvm = llvm_ir[parser_start:parser_end]
        self.assertNotRegex(parser_llvm, r"getelementptr i8, ptr %[^,]+, i64 -1")
        self.assertRegex(parser_llvm, r"sub i64 %[^,]+, 1")
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

    def test_codegen_string_literal_quote_scan_lowers_without_break_lost_phi(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_string_literal_bytes"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("self._string_literal_quote_pos(raw)", method_source)
        self.assertNotIn("enumerate(raw)", method_source)
        self.assertNotIn("break", method_source)
        self.assertIn("def _string_literal_quote_pos", source)
        literal_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_string_literal"
        ]
        self.assertEqual(len(literal_methods), 1)
        literal_source = ast.unparse(literal_methods[0])
        self.assertIn("init_len + 1", literal_source)
        self.assertIn("c.ConstString(data, init_len, False)", literal_source)

    def test_codegen_encode_string_units_lowers_without_comprehension_placeholders(self) -> None:
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
        body = repr(module.functions[0].body)
        self.assertIn("IrForEach", body)
        self.assertNotIn("__ListComp", body)
        self.assertNotIn("__GeneratorExp", body)

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

    def test_codegen_parse_int_value_lowers_without_runtime_int_or_negative_index(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        parse_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_parse_int_value"
        ]
        self.assertEqual(len(parse_methods), 1)
        method = parse_methods[0]
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "int"
                for node in ast.walk(method)
            ),
            "_LLVMGen._parse_int_value should not depend on runtime int(str, base)",
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.UnaryOp)
                and isinstance(node.slice.op, ast.USub)
                for node in ast.walk(method)
            ),
            "_LLVMGen._parse_int_value should not use negative string indexes",
        )

    def test_typemap_require_lowers_without_direct_int_key_subscript(self) -> None:
        source = (ROOT / "src/xcc/sema/symbols.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        require_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "require"
        ]
        self.assertEqual(len(require_methods), 1)
        method = require_methods[0]
        self.assertFalse(
            any(isinstance(node, ast.Subscript) for node in ast.walk(method)),
            "TypeMap.require should not lower dict[id(node)] as tuple indexing",
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

    def test_codegen_declare_func_lowers_param_cache_without_listcomp(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        declare_func_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_declare_func"
        ]
        self.assertEqual(len(declare_func_methods), 1)
        method = declare_func_methods[0]
        self.assertFalse(
            any(isinstance(node, ast.ListComp) for node in ast.walk(method)),
            "_declare_func should cache parameter types through a typed loop",
        )
        self.assertTrue(
            any(
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "stored_param_types"
                for node in ast.walk(method)
            ),
            "_declare_func should annotate stored_param_types before appending values",
        )

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

    def test_codegen_eval_array_init_lowers_zero_fill_without_listcomp(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eval_array_init_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_eval_array_init"
        ]
        self.assertEqual(len(eval_array_init_methods), 1)
        method = eval_array_init_methods[0]
        self.assertFalse(
            any(isinstance(node, ast.ListComp) for node in ast.walk(method)),
            "_eval_array_init should build default element constants through a typed loop",
        )
        self.assertTrue(
            any(
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "elems"
                for node in ast.walk(method)
            ),
            "_eval_array_init should annotate elems before appending values",
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
        self.assertFalse(
            any(isinstance(node, ast.ListComp) for node in ast.walk(method)),
            "_eval_record_path_init should build field constants through a typed loop",
        )

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

    def test_incomplete_record_check_lowers_without_loop_flag_or_dict_membership(self) -> None:
        source = (ROOT / "src/xcc/sema/type_resolution.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "is_invalid_incomplete_record_object_type"
        ]
        self.assertEqual(len(methods), 1)
        method = methods[0]
        method_source = ast.unparse(method)
        self.assertNotIn("for ", method_source)
        self.assertNotIn("not in self._record_definitions", method_source)
        self.assertIn("self._record_members(key) is None", method_source)
        self.assertNotIn("key in self._record_definitions", ast.unparse(tree))
        self.assertNotIn("type_.name not in self._record_definitions", ast.unparse(tree))

    def test_void_object_check_lowers_without_break_latched_flag(self) -> None:
        source = (ROOT / "src/xcc/sema/__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_is_invalid_void_object_type"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertNotIn("break", method_source)
        self.assertNotIn("has_pointer_op", method_source)
        self.assertIn("return False", method_source)
        self.assertIn("return True", method_source)

    def test_scope_record_tags_use_string_keys_for_native_dict_lookup(self) -> None:
        source = (ROOT / "src/xcc/sema/symbols.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"define_record_tag", "lookup_record_tag_current"}
        ]
        self.assertEqual(len(methods), 2)
        for method in methods:
            with self.subTest(method=method.name):
                method_source = ast.unparse(method)
                self.assertIn("kind + ' ' + tag", method_source)
                self.assertFalse(any(isinstance(node, ast.Tuple) for node in ast.walk(method)))

    def test_anonymous_record_names_use_explicit_native_state_updates(self) -> None:
        records_source = (ROOT / "src/xcc/sema/records.py").read_text(encoding="utf-8")
        records_tree = ast.parse(records_source)
        records_functions = {
            node.name: node
            for node in ast.walk(records_tree)
            if isinstance(node, ast.FunctionDef)
        }
        key_source = ast.unparse(records_functions["anonymous_record_key"])
        name_source = ast.unparse(records_functions["record_type_name"])
        self.assertIn("key = type_spec.name", key_source)
        self.assertIn("str(id(member))", key_source)
        self.assertIn("anonymous_record_key(type_spec)", name_source)
        self.assertNotIn("(type_spec.name, type_spec.record_members)", name_source)

        analyzer_source = (ROOT / "src/xcc/sema/__init__.py").read_text(encoding="utf-8")
        analyzer_tree = ast.parse(analyzer_source)
        methods = [
            node
            for node in ast.walk(analyzer_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_record_type_name"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("self._anon_record_counter = result[1]", method_source)
        self.assertIn(
            "self._anon_record_names[anonymous_record_key(type_spec)] = name",
            method_source,
        )
        self.assertNotIn("name, self._anon_record_counter =", method_source)

    def test_scope_parent_lookup_lowers_without_recursive_method_calls(self) -> None:
        source = (ROOT / "src/xcc/sema/symbols.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"lookup_record_tag", "lookup", "lookup_typedef"}
        ]
        self.assertEqual(len(methods), 3)
        for method in methods:
            with self.subTest(method=method.name):
                method_source = ast.unparse(method)
                self.assertIn("while scope is not None", method_source)
                self.assertNotIn(f"self._parent.{method.name}", method_source)

    def test_sema_child_scopes_do_not_depend_on_constructor_parent_argument(self) -> None:
        symbols_source = (ROOT / "src/xcc/sema/symbols.py").read_text(encoding="utf-8")
        symbols_tree = ast.parse(symbols_source)
        helpers = [
            node
            for node in ast.walk(symbols_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "child"
        ]
        self.assertEqual(len(helpers), 1)
        helper_source = ast.unparse(helpers[0])
        self.assertIn("scope = Scope()", helper_source)
        self.assertIn("scope._parent = self", helper_source)
        for module_path in (
            ROOT / "src/xcc/sema/__init__.py",
            ROOT / "src/xcc/sema/statements.py",
            ROOT / "src/xcc/sema/expressions.py",
        ):
            with self.subTest(module=module_path.name):
                source = module_path.read_text(encoding="utf-8")
                self.assertNotIn("Scope(scope)", source)
                self.assertNotIn("Scope(self._file_scope)", source)

    def test_record_member_parser_lowers_supported_break_after_member(self) -> None:
        source = (ROOT / "src/xcc/parser/type_specs.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "parse_record_member_declaration"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("while True:", method_source)
        self.assertIn("break", method_source)
        self.assertNotIn("more_members", method_source)

        class_types = {}
        function_types = {}
        support_modules = {
            "xcc.ast",
            "xcc.lexer",
            "xcc.types",
        }
        for module in collect_bootstrap_sources(ROOT):
            if module.name not in support_modules and not module.name.startswith("xcc.parser"):
                continue
            analysis = analyze_path(module.path)
            class_types.update(analysis.types.classes)
            function_types.update(analysis.types.functions)
        lowered = lower_source_to_ir(
            source,
            filename=str(ROOT / "src/xcc/parser/type_specs.py"),
            include_records=frozenset(),
            include_functions={"parse_record_member_declaration"},
            extra_classes=class_types,
            extra_functions=function_types,
        )
        self.assertEqual(
            [function.name for function in lowered.functions],
            ["parse_record_member_declaration"],
        )
        self.assertIn("IrBreak", repr(lowered.functions[0].body))

    def test_decl_stmt_parser_avoids_break_after_appending_declaration(self) -> None:
        source = (ROOT / "src/xcc/parser/__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_parse_decl_stmt"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertNotIn("while True:", method_source)
        self.assertIn("more_declarations = True", method_source)
        self.assertIn("more_declarations = False", method_source)

    def test_unary_parser_lowers_without_break_latched_operator_flag(self) -> None:
        source = (ROOT / "src/xcc/parser/expressions.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "parse_unary"
        ]
        helpers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_check_unary_operator"
        ]
        self.assertEqual(len(methods), 1)
        self.assertEqual(len(helpers), 1)
        method_source = ast.unparse(methods[0])
        helper_source = ast.unparse(helpers[0])
        self.assertNotIn("has_unary_operator", method_source)
        self.assertNotIn("break", method_source)
        self.assertIn("_check_unary_operator(parser)", method_source)
        self.assertIn("parser._check_punct('!')", helper_source)

    def test_codegen_if_without_else_avoids_conditional_block_side_effect(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_emit_if"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("else_bb = None", method_source)
        self.assertIn("if stmt.else_body is not None", method_source)
        self.assertIn("if else_bb is not None", method_source)
        self.assertNotIn("if stmt.else_body else None", method_source)

    def test_codegen_lookup_local_lowers_without_reversed_scope_iteration(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_lookup_local"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("index = len(self._locals)", method_source)
        self.assertIn("while index > 0", method_source)
        self.assertNotIn("reversed(self._locals)", method_source)
        self.assertIn("self._lookup_local_in_scope(scope, name)", method_source)
        self.assertIn("def _set_current_local", source)
        self.assertIn("def _current_local_contains", source)
        self.assertIn("def _lookup_local_in_scope", source)
        self.assertIn("scope.items()", source)
        self.assertNotIn("name in scope", source)
        self.assertNotIn("current_scope.get", source)
        self.assertNotIn("self._locals[-1]", source)

    def test_codegen_pointer_null_compare_avoids_inttoptr_for_zero_literal(self) -> None:
        source = (ROOT / "src/xcc/codegen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        binary_methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_binary"
        ]
        self.assertEqual(len(binary_methods), 1)
        binary_source = ast.unparse(binary_methods[0])
        self.assertIn("self._compare_pointer_null", binary_source)
        self.assertIn("if null_cmp is not None", binary_source)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_compare"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.unparse(methods[0])
        self.assertIn("right_is_null_pointer_constant", method_source)
        self.assertIn("left_is_null_pointer_constant", method_source)
        self.assertIn("right = c.ConstNull(lt)", method_source)
        self.assertIn("left = c.ConstNull(rt)", method_source)
        self.assertIn("def _is_zero_int_literal", source)
        self.assertIn("def _is_pointer_comparison_type", source)
        self.assertIn("type_.pointer_depth > 0", source)
        self.assertIn("len(type_.array_lengths) > 0", source)
        self.assertIn("c.BuildICmp(self._builder, 32, value, null", source)
        self.assertIn("def _compare_pointer_truth", source)

    def test_sema_integer_literal_parser_avoids_untagged_union_and_global_dicts(self) -> None:
        source = (ROOT / "src/xcc/sema/constants.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        parser_source = ast.unparse(functions["parse_int_literal"])
        candidates_source = ast.unparse(functions["_integer_literal_candidates"])
        limits_source = ast.unparse(functions["fits_integer_literal_value"])
        self.assertIn("lexeme: str", parser_source)
        self.assertNotIn("isinstance(lexeme, int)", parser_source)
        self.assertIn("_integer_literal_candidates(is_decimal, suffix)", parser_source)
        self.assertIn("int(body, 10)", parser_source)
        self.assertNotIn("int(body)", parser_source)
        self.assertNotIn(".get(", parser_source)
        self.assertIn("return (INT, LONG, LLONG)", candidates_source)
        self.assertNotIn(".get(", candidates_source)
        self.assertNotIn(".get(", limits_source)

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
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define ptr @xcc.llvm_api.ptr_array(ptr %values)", llvm_ir)
        self.assertIn("define ptr @xcc.llvm_api.zero_ptr_array(i64 %size)", llvm_ir)
        self.assertIn("define ptr @xcc.llvm_api.optional_zero_ptr_array(i64 %size)", llvm_ir)
        self.assertNotIn("declare ptr @calloc(i64, i64)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_calloc(i64 %len, i64 8)", llvm_ir)
        self.assertNotIn("call ptr @calloc(", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values, i64 %index)", llvm_ir)
        self.assertNotIn("define ptr @xcc.llvm_api.ptr_array(ptr %values) {\nentry:\n  ret ptr null", llvm_ir)

    def test_slice_lowers_imported_global_string_container_membership(self) -> None:
        module = aot_slice.lower_core_slice(
            (
                ROOT / "src/xcc/ast.py",
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
        package_map = aot_slice._module_rename_map(
            "xcc.frontend",
            "from xcc.parser import parse\n"
            "def f() -> int:\n"
            "    return 1\n",
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
            output = ROOT / "build/aot/xcc-b583-build-flags"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b564-object-macro"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b565-object-macro-alias"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b567-macro-regions"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
            source = root / "macro_regions.c"
            obj = root / "macro_regions.o"
            source.write_text(
                "#define SIGNAL 4 /* signal value */\n"
                "/* Codes for SIGNAL */\n"
                "const char *name = \"SIGNAL\"; // SIGNAL\n"
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
            output = ROOT / "build/aot/xcc-b568-integer-condition"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b571-has-include"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b573-undef"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b574-nested-compound"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b575-compatible-typedef"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
            source = root / "compatible_typedef.c"
            obj = root / "compatible_typedef.o"
            source.write_text(
                "typedef void *Pointer;\n"
                "typedef void *Pointer;\n"
                "int main(void) { return 0; }\n",
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
            output = ROOT / "build/aot/xcc-b576-function-macro"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b578-pragma-operator"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b579-signed-alias"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b580-stddef-offsetof"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b584-limits"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b585-atomic-orders"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b587-floating-minima"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b588-enum-constant"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b581-switch-default"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-b582-inferred-global-array"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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

    def test_real_native_bootstrap_accepts_function_pointer_argument(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = ROOT / "build/aot/xcc-b577-function-pointer"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-configure-driver"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
            output = ROOT / "build/aot/xcc-v367"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
            source = root / "missing_include.c"
            obj = root / "missing_include.o"
            source.write_text(
                "#include <xcc_v367_missing_header.h>\n"
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

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Include not found", result.stdout + result.stderr)
            self.assertFalse(obj.exists())

    def test_v368_native_bootstrap_include_next_uses_following_system_root(self) -> None:
        llc = Path("/opt/homebrew/opt/llvm/bin/llc")
        if not llc.exists():
            self.skipTest("llc is not installed at the configured path")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = ROOT / "build/aot/xcc-v368"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
            include_next_source = root / "include_next.c"
            include_next_obj = root / "include_next.o"
            include_next_source.write_text(
                "#include <inttypes.h>\n"
                "int main(void){return 0;}\n",
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
            output = ROOT / "build/aot/xcc-conditional-driver"
            executable = build_native_bootstrap(ROOT, output, llc=str(llc), cc="cc")
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
                "int (*fn)(void *);\n"
                "int main(void){return 0;}\n",
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
                "struct S { void *cookie; int (*close)(void *); };\n"
                "int main(void){return 0;}\n",
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
                "int funopen(int (*)(void *, char *, int));\n"
                "int main(void){return 0;}\n",
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
                "void takes(void *p);\n"
                "int main(void){return 0;}\n",
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
                "int *returns_ptr(void);\n"
                "int main(void){return 0;}\n",
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
