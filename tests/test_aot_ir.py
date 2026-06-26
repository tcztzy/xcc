import unittest
from dataclasses import FrozenInstanceError

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrConstInt,
    IrFunction,
    IrIntType,
    IrModule,
    IrName,
    IrParam,
    IrReturn,
    lower_source_to_ir,
)


class AotIrModelTests(unittest.TestCase):
    def test_ir_module_tracks_records_functions_and_entry(self) -> None:
        int64 = IrIntType(64, signed=True)
        function = IrFunction(
            "answer",
            (),
            int64,
            (IrReturn(IrConstInt(42, int64)),),
        )
        module = IrModule("sample.py", (), (function,), entry="answer")
        self.assertEqual(module.filename, "sample.py")
        self.assertEqual(module.records, ())
        self.assertEqual(module.functions, (function,))
        self.assertEqual(module.entry, "answer")

    def test_ir_statement_values_are_immutable(self) -> None:
        int64 = IrIntType(64, signed=True)
        statement = IrAssign(
            "total",
            IrBinary("+", IrConstInt(1, int64), IrConstInt(2, int64), int64),
        )
        with self.assertRaises(FrozenInstanceError):
            statement.target = "other"  # type: ignore[misc]

    def test_function_parameter_shape_is_explicit(self) -> None:
        int64 = IrIntType(64, signed=True)
        function = IrFunction(
            "identity",
            (IrParam("value", int64),),
            int64,
            (IrReturn(IrConstInt(0, int64)),),
        )
        self.assertEqual(function.params[0].name, "value")
        self.assertEqual(function.params[0].type, int64)


class AotScalarLoweringTests(unittest.TestCase):
    def test_lowers_int64_return_constant(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            filename="scalar.py",
            entry="answer",
        )
        function = module.functions[0]
        self.assertEqual(function.name, "answer")
        self.assertEqual(function.return_type.bits, 64)
        self.assertEqual(function.body[0].value.value, 42)

    def test_lowers_parameter_binary_return(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef add(left: int64, right: int64) -> int64:\n    return left + right\n",
            filename="add.py",
            entry="add",
        )
        function = module.functions[0]
        self.assertEqual([param.name for param in function.params], ["left", "right"])
        returned = function.body[0].value
        self.assertIsInstance(returned, IrBinary)
        self.assertEqual(returned.op, "+")
        self.assertEqual(returned.left, IrName("left", function.params[0].type))

    def test_rejects_unsupported_expression(self) -> None:
        with self.assertRaises(AotError) as ctx:
            lower_source_to_ir(
                "int64 = int\ndef f() -> int64:\n    return -1\n",
                filename="bad.py",
                entry="f",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

    def test_lowers_dataclass_record_layout_and_field_read(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "def use(pair: Pair) -> int64:\n"
            "    return pair.left + pair.right\n"
        )
        module = lower_source_to_ir(source, filename="pair.py", entry="use")
        self.assertEqual(module.records[0].name, "Pair")
        self.assertEqual([field.name for field in module.records[0].fields], ["left", "right"])
        returned = module.functions[0].body[0].value
        self.assertEqual(returned.left.field, "left")
        self.assertEqual(returned.right.field, "right")

    def test_lowers_record_constructor_and_method_call(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "    def total(self) -> int64:\n"
            "        return self.left + self.right\n"
            "def entry() -> int64:\n"
            "    pair = Pair(2, 3)\n"
            "    return pair.total()\n"
        )
        module = lower_source_to_ir(source, filename="method.py", entry="entry")
        self.assertEqual([function.name for function in module.functions], ["Pair.total", "entry"])
        self.assertEqual(module.functions[1].body[0].target, "pair")
        self.assertEqual(module.functions[1].body[1].value.target, "Pair.total")


if __name__ == "__main__":
    unittest.main()
