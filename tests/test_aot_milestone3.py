import ast
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrBoolType,
    IrBranch,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstString,
    IrForEach,
    IrFunction,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrPrint,
    IrRaise,
    IrReturn,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    analyze_path,
    collect_slice_inputs,
    emit_llvm_text,
    lower_source_to_ir,
)
from xcc.aot.core_runtime import runtime_prelude
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
        self.assertEqual(IrTupleSlice(IrName("parts", tuple_type), 1, None).type, tuple_type)

    def test_models_core_control_flow_and_status(self) -> None:
        int64 = IrIntType(64, signed=True)
        branch = IrBranch((IrReturn(IrConstInt(1, int64)),))
        node = IrIf(IrConstBool(True), branch, IrBranch((IrReturn(IrConstInt(0, int64)),)))
        loop = IrForEach("item", IrName("items", IrTupleType((IrStringType(),))), branch)
        self.assertEqual(node.then_branch.statements[0].value.value, 1)
        self.assertEqual(loop.target, "item")
        self.assertEqual(IrRaise("ValueError", IrConstString("bad")).exception, "ValueError")
        self.assertEqual(IrPrint(IrConstString("ok")).value.value, "ok")

    def test_core_runtime_prelude_declares_string_helpers(self) -> None:
        prelude = runtime_prelude()
        self.assertIn("declare i32 @puts(ptr)", prelude)
        self.assertIn("define ptr @__xcc_aot_string_concat2", prelude)
        self.assertIn("call i64 @strlen", prelude)
        self.assertIn("call ptr @malloc", prelude)
        self.assertIn("call ptr @memcpy", prelude)
        self.assertIn("store i8 0", prelude)

    def test_annotation_name_edge_forms(self) -> None:
        string_annotation = ast.parse('def f() -> "Type | None":\n    pass\n').body[0].returns
        tuple_expr = ast.parse("value = (int, str)\n").body[0].value
        attribute_annotation = (
            ast.parse("def f(value: module.Type) -> int:\n    pass\n")
            .body[0]
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


if __name__ == "__main__":
    unittest.main()
