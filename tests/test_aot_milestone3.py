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
    IrBreak,
    IrBranch,
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
    _expr_record_names,
    _expr_call_targets,
    _function_record_names,
    _rename_expr_call,
    _rename_statement_calls,
    _statement_record_names,
    _statement_call_targets,
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
        self.assertEqual(_function_record_names(function), ("Box", "Enum", "Other"))
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

    def test_v391_startswith_does_not_retain_phase_pointer(self) -> None:
        llvm_ir = (
            '@v391_prefix = private constant [2 x i8] c"a\\00"\n'
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
            + "    ptr %first, ptr @v391_prefix, i64 0)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %first_mark)\n"
            + "  %second_mark = call ptr @__xcc_aot_phase_mark()\n"
            + "  %second = call ptr @__xcc_aot_alloc(i64 2)\n"
            + "  store i8 120, ptr %second\n"
            + "  %second1 = getelementptr i8, ptr %second, i64 1\n"
            + "  store i8 0, ptr %second1\n"
            + "  %second_ok = call i1 @__xcc_aot_string_startswith(\n"
            + "    ptr %second, ptr @v391_prefix, i64 0)\n"
            + "  call void @__xcc_aot_phase_reset(ptr %second_mark)\n"
            + "  %second_false = xor i1 %second_ok, true\n"
            + "  %ok = and i1 %first_ok, %second_false\n"
            + "  %result = select i1 %ok, i32 0, i32 1\n"
            + "  ret i32 %result\n"
            + "}\n"
        )
        self.assertNotIn("__xcc_aot_startswith_text", llvm_ir)
        with tempfile.TemporaryDirectory() as tmp:
            executable = compile_llvm_executable(
                llvm_ir,
                Path(tmp) / "startswith-phase-pointer",
                filename="startswith-phase-pointer.ll",
            )
            completed = subprocess.run((str(executable),), check=False)

        self.assertEqual(completed.returncode, 0)

    def test_annotation_name_edge_forms(self) -> None:
        string_annotation = parse_source(
            'def f() -> "Type | None":\n    pass\n'
        ).tree.body[0].returns
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
