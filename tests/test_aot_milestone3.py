import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBranch,
    IrBreak,
    IrCall,
    IrConstBool,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstString,
    IrContinue,
    IrEnumMember,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrPrint,
    IrRaise,
    IrRecordType,
    IrReturn,
    IrSetItem,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrWhile,
    analyze_path,
    collect_slice_inputs,
    compile_llvm_executable,
    core_entry_wrapper,
    core_slice_entry_module,
    emit_llvm_text,
    lower_core_slice,
    lower_source_to_ir,
    parse_source,
    run_native_core_smoke,
)
from xcc.aot.core_runtime import runtime_prelude
from xcc.aot.slice import (
    _expr_call_targets,
    _expr_record_names,
    _function_call_targets,
    _function_record_names,
    _rename_expr_call,
    _rename_statement_calls,
    _statement_call_targets,
    _statement_record_names,
)
from xcc.aot.types import annotation_name

ROOT = Path(__file__).resolve().parents[1]
CORE_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/diag.py",
    ROOT / "src/xcc/options.py",
)


class AotMilestone3SliceTests(unittest.TestCase):
    def test_collects_core_slice_in_deterministic_order(self) -> None:
        modules = collect_slice_inputs(CORE_SLICE)
        self.assertEqual(
            [module.name for module in modules],
            ["xcc.diag", "xcc.options", "xcc.types"],
        )
        self.assertEqual(
            [module.path.name for module in modules],
            ["diag.py", "options.py", "types.py"],
        )

    def test_rejects_module_outside_src_xcc(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_slice_inputs((ROOT / "tests/test_aot.py",))
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SLICE-0001")

    def test_rejects_non_python_file_inside_src_xcc(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_slice_inputs((ROOT / "src/xcc/not_python.txt",))
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SLICE-0001")

    def test_core_slice_entry_module_ignores_duplicate_and_missing_call_targets(self) -> None:
        none_type = IrNoneType()
        wrapper = IrFunction(
            "__entry",
            (),
            none_type,
            (
                IrAssign("__first", IrCall("leaf", (), none_type)),
                IrAssign("__missing", IrCall("missing", (), none_type)),
                IrAssign("__second", IrCall("leaf", (), none_type)),
            ),
        )
        module = IrModule("synthetic", (), (IrFunction("leaf", (), none_type, ()),))
        entry_module = core_slice_entry_module(module, wrapper)
        self.assertEqual(
            [function.name for function in entry_module.functions], ["leaf", "__entry"]
        )

    def test_core_slice_walkers_cover_compound_ir_shapes(self) -> None:
        int64 = IrIntType(64, signed=True)
        string_tuple = IrTupleType((IrStringType(),))
        call = IrCall("local", (IrConstString("x"),), IrStringType())
        statements = (
            IrAssign("sum", IrBinary("+", IrConstInt(1, int64), IrConstInt(2, int64), int64)),
            IrAssign(
                "field",
                IrGetField(IrName("box", IrRecordType("Box")), "value", int64),
            ),
            IrAssign(
                "slice",
                IrTupleSlice(IrTuple((call,), string_tuple), IrConstInt(0, int64), None),
            ),
            IrAssign("enum", IrEnumMember("Kind", "EOF")),
            IrAssign(
                "join",
                IrStringJoin(IrConstString(","), IrTuple((call,), string_tuple)),
            ),
            IrPrint(call),
            IrContinue(),
            IrBreak(),
            IrRaise("ValueError", IrStringConcat((call,))),
            IrWhile(IrCall("cond", (), IrBoolType()), IrBranch((IrPrint(call),))),
            IrSetItem(IrName("items", string_tuple), call, call),
        )
        rewritten = _rename_statement_calls(statements, {"local": "xcc.local"})
        self.assertIn("target='xcc.local'", repr(rewritten))
        self.assertNotIn("target='local'", repr(rewritten))

        if_statement = IrIf(
            IrCall("cond", (), IrBoolType()),
            IrBranch((IrPrint(call),)),
            None,
        )
        self.assertEqual(_statement_call_targets(if_statement), ("cond", "local"))
        if_else_statement = IrIf(
            IrCall("cond", (), IrBoolType()),
            IrBranch((IrPrint(call),)),
            IrBranch((IrRaise("ValueError", call),)),
        )
        self.assertEqual(_statement_call_targets(if_else_statement), ("cond", "local", "local"))
        function = IrFunction("walk", (), IrNoneType(), (if_else_statement,))
        with patch(
            "xcc.aot.slice._statement_call_targets",
            wraps=_statement_call_targets,
        ) as normalized_statement_walk:
            self.assertEqual(_function_call_targets(function), ("cond", "local", "local"))
        self.assertEqual(normalized_statement_walk.call_count, 0)
        self.assertEqual(
            _statement_call_targets(
                IrForEach("item", IrTuple((call,), string_tuple), IrBranch(()))
            ),
            ("local",),
        )
        self.assertEqual(
            _statement_call_targets(
                IrWhile(IrCall("cond", (), IrBoolType()), IrBranch((IrPrint(call),)))
            ),
            ("cond", "local"),
        )
        self.assertEqual(_statement_call_targets(IrBreak()), ())
        self.assertEqual(_statement_call_targets(IrContinue()), ())
        self.assertEqual(
            _statement_call_targets(IrSetItem(IrName("items", string_tuple), call, call)),
            ("local", "local"),
        )
        self.assertEqual(
            _expr_call_targets(IrBinary("+", call, call, IrStringType())),
            ("local", "local"),
        )
        self.assertEqual(
            _expr_call_targets(
                IrTupleSlice(IrTuple((call,), string_tuple), IrConstInt(0, int64), None)
            ),
            ("local",),
        )
        self.assertEqual(
            _expr_call_targets(IrStringJoin(IrConstString(","), IrTuple((call,), string_tuple))),
            ("local",),
        )
        with self.assertRaises(AssertionError):
            _rename_statement_calls((object(),), {})  # type: ignore[arg-type]
        with self.assertRaises(AssertionError):
            _rename_expr_call(object(), {})  # type: ignore[arg-type]
        with self.assertRaises(AssertionError):
            _statement_call_targets(object())  # type: ignore[arg-type]
        with self.assertRaises(AssertionError):
            _expr_call_targets(object())  # type: ignore[arg-type]

    def test_core_slice_record_walkers_cover_compound_ir_shapes(self) -> None:
        box_type = IrRecordType("Box")
        other_type = IrRecordType("Other")
        tuple_type = IrTupleType((box_type,))
        call = IrCall("local", (IrName("box", box_type),), other_type)
        statements = (
            IrIf(
                IrName("cond", IrBoolType()),
                IrBranch((IrAssign("then_value", IrName("box", box_type)),)),
                IrBranch((IrReturn(IrName("other", other_type)),)),
            ),
            IrForEach(
                "item",
                IrName("items", tuple_type),
                IrBranch((IrPrint(IrName("box", box_type)),)),
            ),
            IrAssign("enum", IrEnumMember("Kind", "EOF")),
            IrContinue(),
            IrBreak(),
            IrWhile(
                IrName("box", box_type),
                IrBranch((IrPrint(IrName("other", other_type)),)),
            ),
            IrAssign(
                "binary",
                IrBinary(
                    "+",
                    IrName("left", box_type),
                    IrName("right", other_type),
                    box_type,
                ),
            ),
            IrAssign("field", IrGetField(IrName("box", box_type), "value", other_type)),
            IrAssign(
                "slice",
                IrTupleSlice(
                    IrName("items", tuple_type),
                    IrConstInt(0, IrIntType(64, signed=True)),
                    None,
                ),
            ),
            IrSetItem(
                IrName("items", tuple_type),
                IrName("box", box_type),
                IrName("other", other_type),
            ),
            IrAssign(
                "join",
                IrStringJoin(
                    IrConstString(","),
                    IrTuple((IrName("box", box_type),), tuple_type),
                ),
            ),
            IrRaise("ValueError", call),
        )
        function = IrFunction(
            "walk",
            (IrParam("box", box_type),),
            other_type,
            statements,
        )
        with patch(
            "xcc.aot.slice._statement_record_names",
            wraps=_statement_record_names,
        ) as normalized_statement_walk:
            self.assertEqual(_function_record_names(function), ("Box", "Enum", "Other"))
        self.assertEqual(normalized_statement_walk.call_count, 0)
        self.assertEqual(
            _expr_record_names(IrCall("__llvm_api", (), IrRecordType("LLVMApi"))),
            (),
        )
        self.assertEqual(_expr_record_names(IrConstFloat(0.0)), ())
        with self.assertRaises(AssertionError):
            _statement_record_names(object())  # type: ignore[arg-type]
        unknown_expr = type("UnknownExpr", (), {"type": IrStringType()})()
        with self.assertRaises(AssertionError):
            _expr_record_names(unknown_expr)  # type: ignore[arg-type]


class AotMilestone3AnnotationTests(unittest.TestCase):
    def test_analyzes_core_slice_annotations(self) -> None:
        for path in CORE_SLICE:
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.summary.functions), 0)

    def test_binds_type_aliases_and_bases(self) -> None:
        analysis = analyze_path(ROOT / "src/xcc/types.py")
        self.assertIn("Type", analysis.types.classes)
        self.assertIn("FunctionParams", analysis.types.aliases)
        self.assertEqual(
            analysis.types.aliases["FunctionParams"].name,
            "tuple[tuple['Type', ...] | None, bool]",
        )

    def test_preserves_optional_int_parameter_annotation(self) -> None:
        module = lower_source_to_ir(
            "def f(value: int | None) -> int:\n    return value\n",
            filename="optional.py",
        )
        self.assertEqual(module.functions[0].params[0].type, IrRecordType("int | None"))


class AotMilestone3IrTests(unittest.TestCase):
    def test_models_core_value_types_and_string_operations(self) -> None:
        tuple_type = IrTupleType((IrStringType(), IrBoolType()))
        tuple_expr = IrTuple((IrConstString("x"), IrConstBool(True)), tuple_type)
        self.assertEqual(tuple_expr.type, tuple_type)
        self.assertEqual(IrConstBool(False).type, IrBoolType())
        self.assertEqual(IrConstNone().type, IrNoneType())
        self.assertEqual(
            IrStringConcat((IrConstString("a"), IrConstString("b"))).type,
            IrStringType(),
        )
        self.assertEqual(
            IrStringJoin(IrConstString(","), IrName("parts", tuple_type)).type,
            IrStringType(),
        )
        self.assertEqual(
            IrTupleSlice(
                IrName("parts", tuple_type),
                IrConstInt(1, IrIntType(64, signed=True)),
                None,
            ).type,
            tuple_type,
        )

    def test_models_core_control_flow_and_status(self) -> None:
        int64 = IrIntType(64, signed=True)
        branch = IrBranch((IrReturn(IrConstInt(1, int64)),))
        node = IrIf(IrConstBool(True), branch, IrBranch((IrReturn(IrConstInt(0, int64)),)))
        loop = IrForEach("item", IrName("items", IrTupleType((IrStringType(),))), branch)
        while_loop = IrWhile(IrConstBool(True), branch)
        self.assertEqual(node.then_branch.statements[0].value.value, 1)
        self.assertEqual(loop.target, "item")
        self.assertEqual(while_loop.body, branch)
        self.assertEqual(IrBreak(), IrBreak())
        self.assertEqual(IrContinue(), IrContinue())
        self.assertEqual(IrEnumMember("TokenKind", "EOF").type, IrRecordType("Enum"))
        self.assertEqual(IrRaise("ValueError", IrConstString("bad")).exception, "ValueError")
        self.assertEqual(IrPrint(IrConstString("ok")).value.value, "ok")

    def test_core_runtime_prelude_declares_string_helpers(self) -> None:
        prelude = runtime_prelude()
        self.assertIn("declare i32 @puts(ptr)", prelude)
        self.assertIn("define ptr @__xcc_aot_string_concat2", prelude)
        self.assertIn("call i64 @strlen", prelude)
        self.assertIn("call ptr @__xcc_aot_alloc", prelude)
        self.assertIn("call ptr @memcpy", prelude)
        self.assertIn("store i8 0", prelude)
        self.assertIn("define ptr @__xcc_aot_lexer_token_summary_for_source", prelude)
        self.assertIn("define ptr @__xcc_aot_lexer_header_summary_for_source", prelude)
        self.assertIn("define ptr @__xcc_aot_lexer_error_summary_for_source", prelude)
        self.assertIn("@__xcc_aot_fmt_token", prelude)

    def test_string_join_measures_then_allocates_once(self) -> None:
        prelude = runtime_prelude()
        string_join = prelude.split(
            "define ptr @__xcc_aot_string_join(ptr %separator, ptr %values) {",
            1,
        )[1].split("\n}\n", 1)[0]

        self.assertIn("join_measure_cond:", string_join)
        self.assertIn("join_copy_cond:", string_join)
        self.assertEqual(string_join.count("call ptr @__xcc_aot_alloc"), 1)
        self.assertEqual(string_join.count("call ptr @memcpy"), 2)
        self.assertNotIn("@__xcc_aot_string_concat2", string_join)

    def test_allocation_limit_fails_before_requesting_memory(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %out = call ptr @__xcc_aot_alloc(i64 536870913)\n"
            + "  ret i32 0\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "allocation-limit",
                filename="allocation-limit.ll",
            )
            completed = subprocess.run(
                (str(executable),),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 70)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "xcc-aot: allocation limit exceeded\n")

    def test_v392_single_byte_string_cache_is_stable_and_unaccounted(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %first = call ptr @__xcc_aot_single_byte_string(i8 65)\n"
            + "  %second = call ptr @__xcc_aot_single_byte_string(i8 65)\n"
            + "  %after = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %same = icmp eq ptr %first, %second\n"
            + "  %byte = load i8, ptr %first\n"
            + "  %right_byte = icmp eq i8 %byte, 65\n"
            + "  %nul_ptr = getelementptr i8, ptr %first, i64 1\n"
            + "  %nul = load i8, ptr %nul_ptr\n"
            + "  %terminated = icmp eq i8 %nul, 0\n"
            + "  %balanced = icmp eq i64 %after, %baseline\n"
            + "  %stable = and i1 %same, %right_byte\n"
            + "  %valid = and i1 %terminated, %balanced\n"
            + "  %ok = and i1 %stable, %valid\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "single-byte-string-cache",
                filename="single-byte-string-cache.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_tuple_backing_uses_a_stable_handle_without_global_forwarding_tables(self) -> None:
        prelude = runtime_prelude()
        resolver = prelude.split(
            "define ptr @__xcc_aot_tuple_resolve(ptr %tuple) {",
            1,
        )[1].split("define void @__xcc_aot_tuple_forward", 1)[0]

        self.assertNotIn("call ptr @__xcc_aot_tuple_resolve", resolver)
        self.assertIn("ret ptr %tuple", resolver)
        self.assertNotIn("@__xcc_aot_tuple_aliases", prelude)
        self.assertNotIn("@__xcc_aot_tuple_capacities", prelude)
        self.assertNotIn("@__xcc_aot_tuple_object_layouts", prelude)
        self.assertIn("define ptr @__xcc_aot_tuple_new(i64 %length)", prelude)
        self.assertIn("call ptr @__xcc_aot_realloc", prelude)

    def test_tuple_append_keeps_the_original_handle(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %tuple = call ptr @__xcc_aot_tuple_new(i64 0)\n"
            + "  %appended = call ptr @__xcc_aot_tuple_append(ptr %tuple, ptr null)\n"
            + "  %same = icmp eq ptr %tuple, %appended\n"
            + "  %length = call i64 @__xcc_aot_tuple_len(ptr %tuple)\n"
            + "  %right_length = icmp eq i64 %length, 1\n"
            + "  %ok = and i1 %same, %right_length\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "stable-tuple-handle",
                filename="stable-tuple-handle.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v388_phase_reset_reclaims_owned_allocations(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %persistent = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %persistent_resized = call ptr @__xcc_aot_realloc(\n"
            + "    ptr %persistent, i64 64, i64 64)\n"
            + "  %outer = call ptr @__xcc_aot_alloc(i64 16)\n"
            + "  %inner_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %outer_resized = call ptr @__xcc_aot_realloc(\n"
            + "    ptr %outer, i64 16, i64 64)\n"
            + "  %inner_probe = call ptr @__xcc_aot_alloc(i64 32)\n"
            + "  %peak = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_reset(ptr %inner_mark)\n"
            + "  %after_inner = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %inner_reclaimed = icmp ult i64 %after_inner, %peak\n"
            + "  store i64 41, ptr %outer_resized\n"
            + "  %outer_value = load i64, ptr %outer_resized\n"
            + "  %outer_survived = icmp eq i64 %outer_value, 41\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer_mark)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  store i64 42, ptr %persistent_resized\n"
            + "  %persistent_value = load i64, ptr %persistent_resized\n"
            + "  %persistent_survived = icmp eq i64 %persistent_value, 42\n"
            + "  %inner_ok = and i1 %inner_reclaimed, %outer_survived\n"
            + "  %outer_ok = and i1 %balanced, %persistent_survived\n"
            + "  %ok = and i1 %inner_ok, %outer_ok\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-reset",
                filename="phase-reset.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v389_phase_reset_rejects_non_lifo_mark_before_release(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %outer_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %outer_value = call ptr @__xcc_aot_alloc(i64 32)\n"
            + "  %inner_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %inner_value = call ptr @__xcc_aot_alloc(i64 32)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer_mark)\n"
            + "  ret i32 0\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-reset-non-lifo",
                filename="phase-reset-non-lifo.ll",
            )
            completed = subprocess.run(
                (str(executable),), check=False, capture_output=True, text=True
            )

        self.assertEqual(completed.returncode, 70)
        self.assertEqual(completed.stderr, "xcc-aot: memory safety violation\n")

    def test_v405_phase_promotion_search_stops_at_current_mark(self) -> None:
        runtime = runtime_prelude()
        promote_body = runtime.split("define i1 @__xcc_aot_phase_promote(ptr %payload)", 1)[
            1
        ].split("\n}", 1)[0]
        self.assertNotIn("call ptr @__xcc_aot_find_allocation", promote_body)
        self.assertIn("load ptr, ptr @__xcc_aot_allocation_head", promote_body)
        self.assertIn("icmp eq ptr %node, %mark", promote_body)
        llvm_ir = (
            runtime
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %kept = call ptr @__xcc_aot_alloc(i64 16)\n"
            + "  store i64 41, ptr %kept\n"
            + "  %temporary = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  %promoted = call i1 @__xcc_aot_phase_promote(ptr %kept)\n"
            + "  %null_promoted = call i1 @__xcc_aot_phase_promote(ptr null)\n"
            + "  %peak = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_reset(ptr %mark)\n"
            + "  %after_reset = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %temporary_reclaimed = icmp ult i64 %after_reset, %peak\n"
            + "  %value = load i64, ptr %kept\n"
            + "  %value_survived = icmp eq i64 %value, 41\n"
            + "  %resized = call ptr @__xcc_aot_realloc(ptr %kept, i64 16, i64 24)\n"
            + "  store i64 42, ptr %resized\n"
            + "  %resized_value = load i64, ptr %resized\n"
            + "  %resize_survived = icmp eq i64 %resized_value, 42\n"
            + "  call void @__xcc_aot_free(ptr %resized)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %outer_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %outer_kept = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 44, ptr %outer_kept\n"
            + "  %inner_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %nested_kept = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 43, ptr %nested_kept\n"
            + "  %nested_temporary = call ptr @__xcc_aot_alloc(i64 48)\n"
            + "  %outer_not_promoted = call i1 @__xcc_aot_phase_promote(ptr %outer_kept)\n"
            + "  %nested_promoted = call i1 @__xcc_aot_phase_promote(ptr %nested_kept)\n"
            + "  %nested_peak = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_reset(ptr %inner_mark)\n"
            + "  %after_inner = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %inner_temporary_reclaimed = icmp ult i64 %after_inner, %nested_peak\n"
            + "  %nested_value = load i64, ptr %nested_kept\n"
            + "  %nested_value_survived = icmp eq i64 %nested_value, 43\n"
            + "  %outer_value = load i64, ptr %outer_kept\n"
            + "  %outer_value_survived = icmp eq i64 %outer_value, 44\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer_mark)\n"
            + "  %after_outer = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %parent_reclaimed = icmp eq i64 %after_outer, %baseline\n"
            + "  %not_null_promoted = xor i1 %null_promoted, true\n"
            + "  %promotion_ok = and i1 %promoted, %not_null_promoted\n"
            + "  %lifetime_ok = and i1 %temporary_reclaimed, %value_survived\n"
            + "  %cleanup_ok = and i1 %resize_survived, %balanced\n"
            + "  %outer_stayed = xor i1 %outer_not_promoted, true\n"
            + "  %outer_ok = and i1 %outer_stayed, %outer_value_survived\n"
            + "  %nested_survived = and i1 %nested_value_survived, %outer_ok\n"
            + "  %nested_promotion_ok = and i1 %nested_promoted, %nested_survived\n"
            + "  %nested_cleanup_ok = and i1 %inner_temporary_reclaimed, %parent_reclaimed\n"
            + "  %nested_ok = and i1 %nested_promotion_ok, %nested_cleanup_ok\n"
            + "  %partial = and i1 %promotion_ok, %lifetime_ok\n"
            + "  %global_ok = and i1 %partial, %cleanup_ok\n"
            + "  %ok = and i1 %global_ok, %nested_ok\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-promote",
                filename="phase-promote.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v406_phase_commit_transfers_failure_region_to_parent(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  %message = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 41, ptr %message\n"
            + "  %temporary = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  %before_commit = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_commit(ptr %inner)\n"
            + "  %after_commit = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %marker_released = icmp ult i64 %after_commit, %before_commit\n"
            + "  %message_value = load i64, ptr %message\n"
            + "  %message_survived = icmp eq i64 %message_value, 41\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %parent_reclaimed = icmp eq i64 %final, %baseline\n"
            + "  %survived = and i1 %marker_released, %message_survived\n"
            + "  %ok = and i1 %survived, %parent_reclaimed\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-commit",
                filename="phase-commit.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v406_phase_commit_rejects_non_lifo_mark(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  call void @__xcc_aot_phase_commit(ptr %outer)\n"
            + "  ret i32 0\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-commit-non-lifo",
                filename="phase-commit-non-lifo.ll",
            )
            completed = subprocess.run(
                (str(executable),), check=False, capture_output=True, text=True
            )

        self.assertEqual(completed.returncode, 70)
        self.assertEqual(completed.stderr, "xcc-aot: memory safety violation\n")

    def test_v407_capture_promotes_to_owner_region_across_nested_phases(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %owner = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %middle = call ptr @__xcc_aot_phase_mark()\n"
            + "  %middle_temporary = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  %value = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 47, ptr %value\n"
            + "  %target = call ptr @__xcc_aot_phase_capture_target(ptr %owner)\n"
            + "  %right_target = icmp eq ptr %target, %middle\n"
            + "  %promoted = call i1 @__xcc_aot_phase_promote_to(\n"
            + "    ptr %value, ptr %target)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %inner)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %middle)\n"
            + "  %kept = load i64, ptr %value\n"
            + "  %value_survived = icmp eq i64 %kept, 47\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %target_and_move = and i1 %right_target, %promoted\n"
            + "  %survived = and i1 %target_and_move, %value_survived\n"
            + "  %ok = and i1 %survived, %balanced\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-nested",
                filename="phase-capture-nested.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v418_ancestor_capture_defers_complete_mark_chain(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %owner = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %middle = call ptr @__xcc_aot_phase_mark()\n"
            + "  %middle_scratch = call ptr @__xcc_aot_alloc(i64 32)\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  %value = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 61, ptr %value\n"
            + "  %inner_scratch = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  store ptr %value, ptr %owner\n"
            + "  %target = call ptr @__xcc_aot_phase_capture_target(ptr %owner)\n"
            + "  %right_target = icmp eq ptr %target, %middle\n"
            + "  %deferred = call i1 @__xcc_aot_phase_capture_defer(ptr %target)\n"
            + "  %promoted = call i1 @__xcc_aot_phase_promote_to(\n"
            + "    ptr %value, ptr %target)\n"
            + "  %not_promoted = xor i1 %promoted, true\n"
            + "  %before_inner = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_finish(ptr %inner)\n"
            + "  %after_inner = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %expected_inner = sub i64 %before_inner, 40\n"
            + "  %inner_mark_only = icmp eq i64 %after_inner, %expected_inner\n"
            + "  call void @__xcc_aot_phase_finish(ptr %middle)\n"
            + "  %after_middle = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %expected_middle = sub i64 %after_inner, 40\n"
            + "  %middle_mark_only = icmp eq i64 %after_middle, %expected_middle\n"
            + "  %stored = load ptr, ptr %owner\n"
            + "  %kept = load i64, ptr %stored\n"
            + "  %value_survived = icmp eq i64 %kept, 61\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %mode_ok = and i1 %right_target, %deferred\n"
            + "  %walk_skipped = and i1 %mode_ok, %not_promoted\n"
            + "  %marks_only = and i1 %inner_mark_only, %middle_mark_only\n"
            + "  %finish_ok = and i1 %marks_only, %value_survived\n"
            + "  %lifetime_ok = and i1 %finish_ok, %balanced\n"
            + "  %ok = and i1 %walk_skipped, %lifetime_ok\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-deferred-chain",
                filename="phase-capture-deferred-chain.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v415_direct_parent_capture_defers_graph_walk_until_region_finish(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %owner = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  %value = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 53, ptr %value\n"
            + "  %scratch = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  store ptr %value, ptr %owner\n"
            + "  %target = call ptr @__xcc_aot_phase_capture_target(ptr %owner)\n"
            + "  %right_target = icmp eq ptr %target, %inner\n"
            + "  %deferred = call i1 @__xcc_aot_phase_capture_defer(ptr %target)\n"
            + "  %promoted = call i1 @__xcc_aot_phase_promote_to(\n"
            + "    ptr %value, ptr %target)\n"
            + "  %not_promoted = xor i1 %promoted, true\n"
            + "  %before_finish = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_finish(ptr %inner)\n"
            + "  %after_finish = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %expected_after = sub i64 %before_finish, 40\n"
            + "  %marker_released = icmp eq i64 %after_finish, %expected_after\n"
            + "  %stored = load ptr, ptr %owner\n"
            + "  %kept = load i64, ptr %stored\n"
            + "  %value_survived = icmp eq i64 %kept, 53\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %mode_ok = and i1 %right_target, %deferred\n"
            + "  %walk_skipped = and i1 %mode_ok, %not_promoted\n"
            + "  %finish_ok = and i1 %marker_released, %value_survived\n"
            + "  %lifetime_ok = and i1 %finish_ok, %balanced\n"
            + "  %ok = and i1 %walk_skipped, %lifetime_ok\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-deferred-parent",
                filename="phase-capture-deferred-parent.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v416_outermost_owned_return_keeps_exact_promotion(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %value = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  store i64 59, ptr %value\n"
            + "  %scratch = call ptr @__xcc_aot_alloc(i64 64)\n"
            + "  %deferred = call i1 @__xcc_aot_phase_capture_defer(ptr %mark)\n"
            + "  %not_deferred = xor i1 %deferred, true\n"
            + "  %promoted = call i1 @__xcc_aot_phase_promote_to(\n"
            + "    ptr %value, ptr %mark)\n"
            + "  %peak = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  call void @__xcc_aot_phase_finish(ptr %mark)\n"
            + "  %after_finish = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %scratch_reclaimed = icmp ult i64 %after_finish, %peak\n"
            + "  %kept = load i64, ptr %value\n"
            + "  %value_survived = icmp eq i64 %kept, 59\n"
            + "  call void @__xcc_aot_free(ptr %value)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %mode_ok = and i1 %not_deferred, %promoted\n"
            + "  %lifetime_ok = and i1 %scratch_reclaimed, %value_survived\n"
            + "  %cleanup_ok = and i1 %lifetime_ok, %balanced\n"
            + "  %ok = and i1 %mode_ok, %cleanup_ok\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-return-outermost",
                filename="phase-return-outermost.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v413_capture_target_cache_survives_nested_child_phase(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %owner = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %middle = call ptr @__xcc_aot_phase_mark()\n"
            + "  %first = call ptr @__xcc_aot_phase_capture_target(ptr %owner)\n"
            + "  %first_right = icmp eq ptr %first, %middle\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  %poison = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %magic_slot = getelementptr i8, ptr %poison, i64 -8\n"
            + "  %magic = load i64, ptr %magic_slot\n"
            + "  store i64 0, ptr %magic_slot\n"
            + "  %second = call ptr @__xcc_aot_phase_capture_target(ptr %owner)\n"
            + "  %second_right = icmp eq ptr %second, %middle\n"
            + "  store i64 %magic, ptr %magic_slot\n"
            + "  call void @__xcc_aot_phase_reset(ptr %inner)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %middle)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %targets_right = and i1 %first_right, %second_right\n"
            + "  %ok = and i1 %targets_right, %balanced\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-cache-nested",
                filename="phase-capture-cache-nested.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v417_two_owner_cache_survives_alternating_nested_capture(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %baseline = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %outer = call ptr @__xcc_aot_phase_mark()\n"
            + "  %owner_a = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %owner_b = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %middle = call ptr @__xcc_aot_phase_mark()\n"
            + "  %first_a = call ptr @__xcc_aot_phase_capture_target(ptr %owner_a)\n"
            + "  %first_a_right = icmp eq ptr %first_a, %middle\n"
            + "  %first_b = call ptr @__xcc_aot_phase_capture_target(ptr %owner_b)\n"
            + "  %first_b_right = icmp eq ptr %first_b, %middle\n"
            + "  %inner = call ptr @__xcc_aot_phase_mark()\n"
            + "  %poison = call ptr @__xcc_aot_alloc(i64 8)\n"
            + "  %magic_slot = getelementptr i8, ptr %poison, i64 -8\n"
            + "  %magic = load i64, ptr %magic_slot\n"
            + "  store i64 0, ptr %magic_slot\n"
            + "  %second_a = call ptr @__xcc_aot_phase_capture_target(ptr %owner_a)\n"
            + "  %second_a_right = icmp eq ptr %second_a, %middle\n"
            + "  %second_b = call ptr @__xcc_aot_phase_capture_target(ptr %owner_b)\n"
            + "  %second_b_right = icmp eq ptr %second_b, %middle\n"
            + "  store i64 %magic, ptr %magic_slot\n"
            + "  call void @__xcc_aot_phase_reset(ptr %inner)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %middle)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %outer)\n"
            + "  %final = call i64 @__xcc_aot_phase_allocated_bytes()\n"
            + "  %balanced = icmp eq i64 %final, %baseline\n"
            + "  %first_right = and i1 %first_a_right, %first_b_right\n"
            + "  %second_right = and i1 %second_a_right, %second_b_right\n"
            + "  %targets_right = and i1 %first_right, %second_right\n"
            + "  %ok = and i1 %targets_right, %balanced\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-cache-two-owner",
                filename="phase-capture-cache-two-owner.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v413_repeated_nested_capture_preserves_python_semantics(self) -> None:
        source = (
            "def append_value(values: list[str], value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    values.append(value + '-kept')\n"
            "\n"
            "def append_pair(values: list[str]) -> None:\n"
            "    append_value(values, 'first')\n"
            "    append_value(values, 'second')\n"
            "\n"
            "def entry() -> int:\n"
            "    values: list[str] = []\n"
            "    append_pair(values)\n"
            "    first_ok = values[0] == 'first-kept'\n"
            "    second_ok = values[1] == 'second-kept'\n"
            "    return 0 if first_ok and second_ok else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-cache-source.py", entry="entry")
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-cache-source",
                filename="phase-capture-cache-source.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v417_alternating_owner_capture_preserves_python_semantics(self) -> None:
        source = (
            "class Box:\n"
            "    value: str\n"
            "    def __init__(self, value: str) -> None:\n"
            "        self.value = value\n"
            "\n"
            "def update(values: list[str], box: Box, value: str) -> None:\n"
            "    values.append(value + '-first')\n"
            "    box.value = value + '-box-first'\n"
            "    values.append(value + '-second')\n"
            "    box.value = value + '-box-second'\n"
            "\n"
            "def entry() -> int:\n"
            "    values: list[str] = []\n"
            "    box = Box('old')\n"
            "    update(values, box, 'root')\n"
            "    values_ok = values == ['root-first', 'root-second']\n"
            "    return 0 if values_ok and box.value == 'root-box-second' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-two-owner.py", entry="entry")
        )
        self.assertIn("@__xcc_aot_phase_capture_cache_valid_2", llvm_ir)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-two-owner",
                filename="phase-capture-two-owner.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v415_generated_capture_defers_to_parent_region(self) -> None:
        source = (
            "def append_value(values: list[str], value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    values.append(value + '-kept')\n"
            "\n"
            "def entry() -> int:\n"
            "    values: list[str] = []\n"
            "    append_value(values, 'root')\n"
            "    return 0 if values[0] == 'root-kept' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-deferred-source.py", entry="entry")
        )
        capture_helper = llvm_ir.split('define void @"__xcc_aot_phase_capture:', 1)[1].split(
            "\n}", 1
        )[0]
        append_body = llvm_ir.split("define void @append_value(ptr %values, ptr %value)", 1)[
            1
        ].split("\n}", 1)[0]
        self.assertIn("call i1 @__xcc_aot_phase_capture_defer", capture_helper)
        self.assertLess(
            capture_helper.index("call i1 @__xcc_aot_phase_capture_defer"),
            capture_helper.index("__xcc_aot_phase_promote:"),
        )
        self.assertIn("call void @__xcc_aot_phase_finish", append_body)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-deferred-source",
                filename="phase-capture-deferred-source.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v416_owned_return_defers_to_enclosing_region(self) -> None:
        source = (
            "def make(value: str) -> tuple[str, ...]:\n"
            "    scratch = value + '-scratch'\n"
            "    return (value + '-kept',)\n"
            "\n"
            "def entry() -> int:\n"
            "    result = make('root')\n"
            "    return 0 if result[0] == 'root-kept' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-return-deferred-source.py", entry="entry")
        )
        make_body = llvm_ir.split("define ptr @make(ptr %value)", 1)[1].split("\n}", 1)[0]
        defer_index = make_body.index("call i1 @__xcc_aot_phase_capture_defer")
        promote_index = make_body.index('call void @"__xcc_aot_phase_promote:')
        finish_index = make_body.index("call void @__xcc_aot_phase_finish")
        self.assertLess(defer_index, promote_index)
        self.assertLess(promote_index, finish_index)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-return-deferred-source",
                filename="phase-return-deferred-source.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v414_reversed_materialized_enumerate_matches_python(self) -> None:
        source = (
            "def entry() -> int:\n"
            "    values = ('first', 'second')\n"
            "    for index, value in reversed(tuple(enumerate(values))):\n"
            "        return 0 if index == 1 and value == 'second' else 1\n"
            "    return 2\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="reversed-materialized-enumerate.py", entry="entry")
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "reversed-materialized-enumerate",
                filename="reversed-materialized-enumerate.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v407_pointer_store_survives_callee_phase_reset(self) -> None:
        source = (
            "def write(values: list[str], value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    values[0] = value + '-kept'\n"
            "\n"
            "def entry() -> int:\n"
            "    values = ['old']\n"
            "    write(values, 'root')\n"
            "    return 0 if values[0] == 'root-kept' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-store.py", entry="entry")
        )
        write_body = llvm_ir.split("define void @write(ptr %values, ptr %value)", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn("call ptr @__xcc_aot_phase_mark()", write_body)
        self.assertIn('call void @"__xcc_aot_phase_capture:', write_body)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-store",
                filename="phase-capture-store.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v407_record_field_store_survives_callee_phase_reset(self) -> None:
        source = (
            "class Box:\n"
            "    value: str\n"
            "    def __init__(self, value: str) -> None:\n"
            "        self.value = value\n"
            "\n"
            "def write(box: Box, value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    box.value = value + '-kept'\n"
            "\n"
            "def entry() -> int:\n"
            "    box = Box('old')\n"
            "    write(box, 'root')\n"
            "    return 0 if box.value == 'root-kept' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-field.py", entry="entry")
        )
        write_body = llvm_ir.split("define void @write(ptr %box, ptr %value)", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn("getelementptr i8, ptr %box, i64 -8", write_body)
        self.assertIn('call void @"__xcc_aot_phase_capture:', write_body)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-field",
                filename="phase-capture-field.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v407_append_captures_item_and_grown_backing_storage(self) -> None:
        source = (
            "def append_value(values: list[str], value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    values.append(value + '-kept')\n"
            "\n"
            "def entry() -> int:\n"
            "    values: list[str] = []\n"
            "    append_value(values, 'root')\n"
            "    return 0 if values[0] == 'root-kept' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-append.py", entry="entry")
        )
        append_body = llvm_ir.split("define void @append_value(ptr %values, ptr %value)", 1)[
            1
        ].split("\n}", 1)[0]
        self.assertIn('call void @"__xcc_aot_phase_capture:', append_body)
        self.assertIn("call ptr @__xcc_aot_tuple_append", append_body)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-append",
                filename="phase-capture-append.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v408_dict_and_set_mutations_capture_stored_graphs(self) -> None:
        source = (
            "def update(\n"
            "    mapping: dict[str, str], values: set[str], items: list[str], value: str\n"
            ") -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    mapping['key'] = value + '-dict'\n"
            "    mapping.setdefault('default', value + '-default')\n"
            "    incoming: dict[str, str] = {'extra': value + '-extra'}\n"
            "    mapping.update(incoming)\n"
            "    values.add(value + '-set')\n"
            "    additional: set[str] = {value + '-update'}\n"
            "    values.update(additional)\n"
            "    replacement: list[str] = [value + '-slice']\n"
            "    items[:] = replacement\n"
            "\n"
            "def entry() -> int:\n"
            "    mapping: dict[str, str] = {}\n"
            "    values: set[str] = set()\n"
            "    items = ['old']\n"
            "    update(mapping, values, items, 'root')\n"
            "    if mapping['key'] != 'root-dict':\n"
            "        return 1\n"
            "    if mapping['default'] != 'root-default':\n"
            "        return 2\n"
            "    if mapping['extra'] != 'root-extra':\n"
            "        return 3\n"
            "    if 'root-set' not in values or 'root-update' not in values:\n"
            "        return 4\n"
            "    return 0 if items[0] == 'root-slice' else 5\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-containers.py", entry="entry")
        )
        update_body = llvm_ir.split(
            "define void @update(ptr %mapping, ptr %values, ptr %items, ptr %value)", 1
        )[1].split("\n}", 1)[0]
        self.assertIn("call ptr @__xcc_aot_phase_mark()", update_body)
        self.assertGreaterEqual(update_body.count("__xcc_aot_phase_capture:"), 7)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-containers",
                filename="phase-capture-containers.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v408_lazy_global_container_escapes_all_active_phases(self) -> None:
        source = (
            "VALUES: dict[str, str] = {'key': 'stable'}\n"
            "\n"
            "def read() -> str:\n"
            "    scratch = 'temporary' + ' value'\n"
            "    return VALUES['key']\n"
            "\n"
            "def entry() -> int:\n"
            "    first = read()\n"
            "    second = read()\n"
            "    return 0 if first == 'stable' and second == 'stable' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="phase-capture-global.py", entry="entry")
        )
        self.assertIn("@__xcc_aot_global_tuple_0 = private global ptr null", llvm_ir)
        self.assertIn('call void @"__xcc_aot_phase_capture:', llvm_ir)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-capture-global",
                filename="phase-capture-global.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v409_dynamic_object_graphs_survive_callee_phase_reset(self) -> None:
        source = (
            "class Payload:\n"
            "    label: str\n"
            "    def __init__(self, label: str) -> None:\n"
            "        self.label = label\n"
            "\n"
            "class Box:\n"
            "    value: object\n"
            "    def __init__(self) -> None:\n"
            "        self.value = None\n"
            "\n"
            "class OptionalBox:\n"
            "    value: object | None\n"
            "    def __init__(self) -> None:\n"
            "        self.value = None\n"
            "\n"
            "class Base:\n"
            "    label: str\n"
            "    def __init__(self, label: str) -> None:\n"
            "        self.label = label\n"
            "\n"
            "class Child(Base):\n"
            "    def __init__(self, label: str) -> None:\n"
            "        self.label = label\n"
            "\n"
            "def store_text(box: OptionalBox, value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    box.value = value + '-text'\n"
            "\n"
            "def store_tuple(box: Box, value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    box.value = (value + '-tuple',)\n"
            "\n"
            "def store_record(box: Box, value: str) -> None:\n"
            "    scratch = value + '-scratch'\n"
            "    box.value = Payload(value + '-record')\n"
            "\n"
            "def make_child(value: str) -> Base:\n"
            "    scratch = value + '-scratch'\n"
            "    return Child(value + '-child')\n"
            "\n"
            "def make_base(value: str) -> Base:\n"
            "    scratch = value + '-scratch'\n"
            "    return Base(value + '-base')\n"
            "\n"
            "def entry() -> int:\n"
            "    optional_box = OptionalBox()\n"
            "    store_text(optional_box, 'root')\n"
            "    text = optional_box.value\n"
            "    if not isinstance(text, str) or text != 'root-text':\n"
            "        return 1\n"
            "    box = Box()\n"
            "    store_tuple(box, 'root')\n"
            "    items = box.value\n"
            "    if not isinstance(items, tuple):\n"
            "        return 2\n"
            "    typed_items: tuple[str, ...] = items\n"
            "    if typed_items[0] != 'root-tuple':\n"
            "        return 3\n"
            "    store_record(box, 'root')\n"
            "    payload = box.value\n"
            "    if not isinstance(payload, Payload):\n"
            "        return 4\n"
            "    if payload.label != 'root-record':\n"
            "        return 5\n"
            "    child = make_child('root')\n"
            "    if not isinstance(child, Child):\n"
            "        return 6\n"
            "    if child.label != 'root-child':\n"
            "        return 7\n"
            "    base = make_base('root')\n"
            "    if isinstance(base, Child):\n"
            "        return 8\n"
            "    return 0 if base.label == 'root-base' else 9\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="dynamic-object-capture.py", entry="entry")
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "dynamic-object-capture",
                filename="dynamic-object-capture.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v410_native_dict_equality_is_structural_and_order_independent(self) -> None:
        source = (
            "def entry() -> int:\n"
            "    left = {'alpha': (True, False), 'beta': (False, True)}\n"
            "    right = {'beta': (False, True), 'alpha': (True, False)}\n"
            "    if left != right:\n"
            "        return 1\n"
            "    right['alpha'] = (False, False)\n"
            "    if left == right:\n"
            "        return 2\n"
            "    shorter = {'alpha': (True, False)}\n"
            "    if left == shorter:\n"
            "        return 3\n"
            "    return 0\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="dict-equality.py", entry="entry")
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "dict-equality",
                filename="dict-equality.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v389_phase_free_rejects_untracked_pointer_without_prefix_read(self) -> None:
        llvm_ir = (
            runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %ordinary = call ptr @__xcc_aot_alloc(i64 32)\n"
            + "  call void @__xcc_aot_free(ptr %ordinary)\n"
            + "  ret i32 0\n"
            + "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "phase-free-untracked",
                filename="phase-free-untracked.ll",
            )
            completed = subprocess.run(
                (str(executable),), check=False, capture_output=True, text=True
            )

        self.assertEqual(completed.returncode, 70)
        self.assertEqual(completed.stderr, "xcc-aot: memory safety violation\n")

    def test_v390_emitted_owned_phase_resets_across_repeated_calls(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        worker = IrFunction(
            "worker",
            (),
            int64,
            (
                IrAssign(
                    "local",
                    IrTuple((IrConstInt(1, int64),), tuple_type),
                ),
                IrReturn(IrConstInt(0, int64)),
            ),
        )
        entry = IrFunction(
            "entry",
            (),
            int64,
            (
                IrAssign("first", IrCall("worker", (), int64)),
                IrReturn(IrCall("worker", (), int64)),
            ),
        )
        llvm_ir = emit_llvm_text(
            IrModule("owned_phase_exec.py", (), (worker, entry), entry="entry")
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "owned-phase-exec",
                filename="owned-phase-exec.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v403_borrowed_pointer_return_survives_owned_phase_reset(self) -> None:
        source = (
            "def first(values: tuple[str, ...]) -> str:\n"
            '    scratch = ("temporary",)\n'
            "    return values[0]\n"
            "\n"
            "def entry() -> int:\n"
            '    value = first(("kept",))\n'
            '    return 0 if value == "kept" else 1\n'
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="borrowed-phase.py", entry="entry")
        )
        first_body = llvm_ir.split("define ptr @first(ptr %values)", 1)[1].split("\n}", 1)[0]
        self.assertIn("call ptr @__xcc_aot_phase_mark()", first_body)
        self.assertIn("call void @__xcc_aot_phase_finish", first_body)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "borrowed-phase",
                filename="borrowed-phase.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v404_owned_result_graph_is_promoted_before_reset(self) -> None:
        source = (
            "def make(value: str) -> tuple[tuple[str, ...], ...]:\n"
            "    scratch = value + '-temporary'\n"
            "    kept = value + '-kept'\n"
            "    return ((kept,),)\n"
            "\n"
            "def entry() -> int:\n"
            "    result = make('root')\n"
            "    return 0 if result[0][0] == 'root-kept' else 1\n"
        )
        namespace: dict[str, object] = {}
        exec(source, namespace)
        entry = namespace["entry"]
        self.assertTrue(callable(entry))
        self.assertEqual(entry(), 0)

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="owned-phase.py", entry="entry")
        )
        make_body = llvm_ir.split("define ptr @make(ptr %value)", 1)[1].split("\n}", 1)[0]
        promote_index = make_body.index('call void @"__xcc_aot_phase_promote:')
        finish_index = make_body.index("call void @__xcc_aot_phase_finish")
        self.assertLess(promote_index, finish_index)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "owned-phase",
                filename="owned-phase.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_v419_startswith_weak_cache_invalidates_before_drop_and_resize(self) -> None:
        llvm_ir = (
            '@v419_prefix = private constant [2 x i8] c"a\\00"\n'
            '@v419_empty = private constant [1 x i8] c"\\00"\n'
            + runtime_prelude()
            + "\n\ndefine i32 @main() {\n"
            + "entry:\n"
            + "  %first_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %first = call ptr @__xcc_aot_alloc(i64 4)\n"
            + "  store i8 97, ptr %first\n"
            + "  %first1 = getelementptr i8, ptr %first, i64 1\n"
            + "  store i8 98, ptr %first1\n"
            + "  %first2 = getelementptr i8, ptr %first, i64 2\n"
            + "  store i8 99, ptr %first2\n"
            + "  %first3 = getelementptr i8, ptr %first, i64 3\n"
            + "  store i8 0, ptr %first3\n"
            + "  %first_ok = call i1 @__xcc_aot_string_startswith(\n"
            + "    ptr %first, ptr @v419_prefix, i64 0)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %first_mark)\n"
            + "  %after_drop = load ptr, ptr @__xcc_aot_startswith_text\n"
            + "  %drop_cleared = icmp eq ptr %after_drop, null\n"
            + "  %second_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %second = call ptr @__xcc_aot_alloc(i64 2)\n"
            + "  store i8 120, ptr %second\n"
            + "  %second1 = getelementptr i8, ptr %second, i64 1\n"
            + "  store i8 0, ptr %second1\n"
            + "  %second_ok = call i1 @__xcc_aot_string_startswith(\n"
            + "    ptr %second, ptr @v419_empty, i64 2)\n"
            + "  %resized = call ptr @__xcc_aot_realloc(ptr %second, i64 2, i64 8)\n"
            + "  %after_resize = load ptr, ptr @__xcc_aot_startswith_text\n"
            + "  %resize_cleared = icmp eq ptr %after_resize, null\n"
            + "  %resized_ok = call i1 @__xcc_aot_string_startswith(\n"
            + "    ptr %resized, ptr @v419_empty, i64 2)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %second_mark)\n"
            + "  %second_false = xor i1 %second_ok, true\n"
            + "  %resized_false = xor i1 %resized_ok, true\n"
            + "  %drop_ok = and i1 %first_ok, %drop_cleared\n"
            + "  %reuse_ok = and i1 %second_false, %resize_cleared\n"
            + "  %resize_ok = and i1 %reuse_ok, %resized_false\n"
            + "  %ok = and i1 %drop_ok, %resize_ok\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        free_body = llvm_ir.split("define void @__xcc_aot_free", 1)[1].split("\n}\n", 1)[0]
        realloc_body = llvm_ir.split("define internal ptr @__xcc_aot_realloc", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertLess(
            free_body.index("call void @__xcc_aot_startswith_cache_invalidate"),
            free_body.index("call void @free"),
        )
        self.assertEqual(
            realloc_body.count("call void @__xcc_aot_startswith_cache_invalidate"), 2
        )
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "startswith-weak-cache",
                filename="startswith-weak-cache.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_annotation_name_edge_forms(self) -> None:
        string_annotation = (
            parse_source('def f() -> "Type | None":\n    pass\n').tree.body[0].returns
        )
        tuple_expr = parse_source("value = (int, str)\n").tree.body[0].value
        attribute_annotation = (
            parse_source("def f(value: module.Type) -> int:\n    pass\n")
            .tree.body[0]
            .args.args[0]
            .annotation
        )
        self.assertEqual(annotation_name(string_annotation), "Type | None")
        self.assertEqual(annotation_name(tuple_expr), "int, str")
        self.assertEqual(annotation_name(attribute_annotation), "module.Type")


class AotMilestone3LoweringTests(unittest.TestCase):
    def test_lowers_diagnostic_options_and_type_methods(self) -> None:
        cases = (
            (ROOT / "src/xcc/diag.py", "Diagnostic.__str__"),
            (ROOT / "src/xcc/options.py", "FrontendOptions.__post_init__"),
            (ROOT / "src/xcc/types.py", "Type.__str__"),
        )
        for path, entry in cases:
            with self.subTest(path=path.name, entry=entry):
                module = lower_source_to_ir(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                    entry=entry,
                )
                self.assertIn(entry, {function.name for function in module.functions})

    def test_lowers_type_transformation_methods(self) -> None:
        source = (ROOT / "src/xcc/types.py").read_text(encoding="utf-8")
        module = lower_source_to_ir(source, filename="src/xcc/types.py", entry="Type.pointer_to")
        names = {function.name for function in module.functions}
        self.assertIn("Type.pointer_to", names)
        self.assertIn("Type.array_of", names)
        self.assertIn("Type.callable_signature", names)


class AotMilestone3LlvmTests(unittest.TestCase):
    def test_emits_if_print_raise_and_runtime_string_calls(self) -> None:
        int32 = IrIntType(32, signed=True)
        module = IrModule(
            "core_ir.py",
            (),
            (
                IrFunction(
                    "entry",
                    (),
                    int32,
                    (
                        IrIf(
                            IrConstBool(True),
                            IrBranch((IrPrint(IrConstString("ok")),)),
                            IrBranch((IrRaise("ValueError", IrConstString("bad")),)),
                        ),
                        IrReturn(IrConstInt(0, int32)),
                    ),
                ),
            ),
            entry="entry",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("br i1 true", llvm_ir)
        self.assertIn("call i32 @puts", llvm_ir)
        self.assertIn("ret i32 2", llvm_ir)

    def test_emits_string_concat_runtime_call(self) -> None:
        module = IrModule(
            "concat.py",
            (),
            (
                IrFunction(
                    "entry",
                    (),
                    IrStringType(),
                    (IrReturn(IrStringConcat((IrConstString("a"), IrConstString("b")))),),
                ),
            ),
            entry="entry",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("@__xcc_aot_string_concat2", llvm_ir)

    def test_emits_core_slice_modules_to_llvm_text(self) -> None:
        for path in CORE_SLICE:
            with self.subTest(path=path.name):
                module = lower_source_to_ir(path.read_text(encoding="utf-8"), filename=str(path))
                llvm_ir = emit_llvm_text(module)
                self.assertIn("define", llvm_ir)


class AotMilestone3CoreHarnessTests(unittest.TestCase):
    def test_core_entry_wrappers_cover_supported_fixtures(self) -> None:
        options = core_entry_wrapper("xcc.options:FrontendOptions.__post_init__", "bad_std")
        self.assertEqual(options.body[0].value.target, "xcc.options.FrontendOptions.__post_init__")
        type_str = core_entry_wrapper("xcc.types:Type.pointer_array_str", "int_pointer_array")
        self.assertEqual(type_str.body[0].value.target, "xcc.types.Type.__str__")
        with self.assertRaises(AotError) as ctx:
            core_entry_wrapper("xcc.unknown:entry", "missing")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SLICE-0002")

    def test_core_smoke_calls_lowered_entry_symbol(self) -> None:
        def fake_run(cmd, **kwargs):
            command = tuple(str(part) for part in cmd)
            if command[0] == "/tool/llc":
                llvm_ir = Path(command[2]).read_text(encoding="utf-8")
                self.assertIn("@xcc.diag.Diagnostic.__str__", llvm_ir)
                self.assertNotIn("input.c:7:3: parse: expected", llvm_ir)
                Path(command[-1]).write_bytes(b"object")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if command[0] == "cc":
                Path(command[-1]).write_text("#!/bin/sh\nprintf 'ok\\n'\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

        with patch("xcc.aot.native.subprocess.run", side_effect=fake_run):
            result = run_native_core_smoke(
                CORE_SLICE,
                entry="xcc.diag:Diagnostic.__str__",
                fixture="diag_with_location",
                llc="/tool/llc",
                cc="cc",
            )
        self.assertEqual(result.native_stdout, "ok\n")

    def test_core_entry_module_namespaces_calls_and_prunes_unreachable_functions(self) -> None:
        module = lower_core_slice(CORE_SLICE)
        type_str = next(
            function for function in module.functions if function.name == "xcc.types.Type.__str__"
        )
        self.assertIn("target='xcc.types._format_function_params'", repr(type_str.body))
        self.assertNotIn("target='Type._format_function_params'", repr(type_str.body))

        wrapper = core_entry_wrapper("xcc.diag:Diagnostic.__str__", "diag_with_location")
        entry_module = core_slice_entry_module(module, wrapper)
        names = {function.name for function in entry_module.functions}
        self.assertIn("xcc.diag.Diagnostic.__str__", names)
        self.assertIn("__xcc_aot_core_entry", names)
        self.assertNotIn("xcc.types.Type.__str__", names)

        type_wrapper = core_entry_wrapper("xcc.types:Type.pointer_array_str", "int_pointer_array")
        type_entry_module = core_slice_entry_module(module, type_wrapper)
        type_names = {function.name for function in type_entry_module.functions}
        self.assertIn("xcc.types.Type.__str__", type_names)
        self.assertNotIn("xcc.types._format_function_params", type_names)


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotMilestone3CoreNativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_diagnostic_str_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            CORE_SLICE,
            entry="xcc.diag:Diagnostic.__str__",
            fixture="diag_with_location",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "input.c:7:3: parse: expected ';'\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_frontend_options_validation_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            CORE_SLICE,
            entry="xcc.options:FrontendOptions.__post_init__",
            fixture="bad_std",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_returncode, 2)
        self.assertEqual(result.native_stdout, "")
        self.assertIn("Unsupported language standard: c99", result.native_stderr)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_type_pointer_array_str_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            CORE_SLICE,
            entry="xcc.types:Type.pointer_array_str",
            fixture="int_pointer_array",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "int*[4]\n")
        self.assertEqual(result.native_returncode, 0)


if __name__ == "__main__":
    unittest.main()
