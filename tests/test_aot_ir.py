import ast
import unittest
from dataclasses import FrozenInstanceError

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrBoolType,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrFunction,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRecordType,
    IrReturn,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleType,
    lower_source_to_ir,
)
from xcc.aot.lower import _collect_global_names, _Lowerer
from xcc.aot.types import AotClassInfo, AotType


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

    def test_string_constant_exposes_type(self) -> None:
        self.assertEqual(IrConstString("ok").type, IrStringType())


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

    def test_lowers_only_requested_functions(self) -> None:
        module = lower_source_to_ir(
            "def wanted() -> int:\n"
            "    return 1\n"
            "def skipped() -> int:\n"
            "    while True:\n"
            "        continue\n"
            "    return 0\n",
            filename="filtered.py",
            include_functions={"wanted"},
        )
        self.assertEqual([function.name for function in module.functions], ["wanted"])

    def test_lowers_only_requested_records(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Wanted:\n"
            "    value: int\n"
            "@dataclass(frozen=True)\n"
            "class Skipped:\n"
            "    value: object\n"
            "def wanted() -> int:\n"
            "    return 1\n",
            filename="record_filter.py",
            include_records={"Wanted"},
            include_functions={"wanted"},
        )
        self.assertEqual([record.name for record in module.records], ["Wanted"])
        self.assertEqual([function.name for function in module.functions], ["wanted"])

    def test_lowers_supported_container_annotation_shapes(self) -> None:
        module = lower_source_to_ir(
            "from collections.abc import Iterable, Sequence\n"
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Containers:\n"
            "    lookup: dict[str, int]\n"
            "    names: set[str]\n"
            "    frozen_names: frozenset[str]\n"
            "    iterable_names: Iterable[str]\n"
            "    sequence_names: Sequence[str]\n"
            "def build(value: Containers) -> tuple[str, ...]:\n"
            "    return ()\n",
            filename="containers.py",
        )
        record = module.records[0]
        self.assertEqual(
            [field.name for field in record.fields],
            ["lookup", "names", "frozen_names", "iterable_names", "sequence_names"],
        )
        self.assertTrue(all(isinstance(field.type, IrTupleType) for field in record.fields))

    def test_lowers_bodyless_requested_function_signature(self) -> None:
        module = lower_source_to_ir(
            "def native_leaf(value: str) -> str:\n"
            "    while True:\n"
            "        continue\n",
            filename="bodyless.py",
            include_functions={"native_leaf"},
            bodyless_functions={"native_leaf"},
        )
        function = module.functions[0]
        self.assertEqual(function.name, "native_leaf")
        self.assertEqual(function.params[0].type, IrStringType())
        self.assertEqual(function.return_type, IrStringType())
        self.assertEqual(function.body, ())

    def test_lowers_plain_int_uint_subtract_and_multiply(self) -> None:
        module = lower_source_to_ir(
            "uint32 = int\n"
            "usize = int\n"
            "def plain() -> int:\n"
            "    return 7\n"
            "def sub(left: uint32, right: uint32) -> uint32:\n"
            "    return left - right\n"
            "def mul(left: uint32, right: uint32) -> uint32:\n"
            "    return left * right\n"
            "def size() -> usize:\n"
            "    return 1\n",
            filename="ops.py",
        )
        self.assertEqual(module.functions[0].return_type, IrIntType(64, signed=True))
        self.assertEqual(module.functions[1].return_type, IrIntType(32, signed=False))
        self.assertEqual(module.functions[1].body[0].value.op, "-")
        self.assertEqual(module.functions[2].body[0].value.op, "*")
        self.assertEqual(module.functions[3].return_type, IrIntType(64, signed=False))

    def test_rejects_unsupported_expression(self) -> None:
        with self.assertRaises(AotError) as ctx:
            lower_source_to_ir(
                "int64 = int\ndef f() -> int64:\n    return -1\n",
                filename="bad.py",
                entry="f",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

    def test_rejects_unknown_name_call_target_and_field_access(self) -> None:
        cases = (
            ("def f() -> int:\n    return missing\n", "XCC-AOT-LOWER-0002"),
            ("def f() -> int:\n    return 1.5\n", "XCC-AOT-LOWER-0002"),
            ("def f() -> int:\n    return helper()\n", "XCC-AOT-LOWER-0003"),
            ("def f(values: tuple[str, ...]) -> str:\n    return str(**values)\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> int:\n    return value.real\n", "XCC-AOT-LOWER-0002"),
            (
                "from dataclasses import dataclass\n"
                "@dataclass(frozen=True)\n"
                "class Pair:\n"
                "    value: int\n"
                "def f(pair: Pair) -> int:\n"
                "    return pair.missing\n",
                "XCC-AOT-LOWER-0002",
            ),
        )
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(AotError) as ctx:
                    lower_source_to_ir(source, filename="bad.py", entry="f")
                self.assertEqual(ctx.exception.diagnostics[0].code, code)

    def test_star_project_import_does_not_bind_call_target_name(self) -> None:
        module = lower_source_to_ir(
            "from xcc.frontend import *\n"
            "def f() -> int:\n"
            "    return 1\n",
            filename="star_import.py",
            entry="f",
        )
        self.assertEqual(module.functions[0].name, "f")

    def test_direct_lowerer_reports_missing_and_unsupported_forms(self) -> None:
        lowerer = _Lowerer("direct.py", {})
        missing_param = ast.parse("def f(value) -> int:\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(missing_param, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")

        missing_return = ast.parse("def f():\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(missing_return, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].message, "Missing lowered annotation")

        unsupported_return = ast.parse("def f() -> float:\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_return, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

        unsupported_string_return = ast.parse('def f() -> "int":\n    return 1\n').body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_string_return, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

        unsupported_call = ast.parse("def f(value: int) -> int:\n    return value.bits()\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_call, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0003")

        unsupported_dynamic_call = ast.parse("def f() -> int:\n    return (lambda: 1)()\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_dynamic_call, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0003")

        missing_kwonly = ast.parse("def f(*, flag) -> int:\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(missing_kwonly, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")

        chained_compare = ast.parse(
            "def f(left: int, middle: int, right: int) -> bool:\n    return left < middle < right\n"
        ).body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(chained_compare, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0004")

        malformed_fstring = ast.JoinedStr([ast.Name("value", ast.Load())])
        with self.assertRaises(AotError) as ctx:
            lowerer._lower_joined_str(malformed_fstring, {})
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0005")

        unsupported_statement = ast.parse("def f() -> int:\n    pass\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_statement, owner=None)
        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "Unsupported lowered statement: Pass",
        )

    def test_direct_lowerer_maps_string_int_and_record_field_types(self) -> None:
        lowerer = _Lowerer(
            "record.py",
            {
                "Node": AotClassInfo(
                    "Node",
                    {
                        "name": AotType("str"),
                        "count": AotType("int"),
                        "next": AotType("Node"),
                    },
                )
            },
        )
        record = lowerer.lower_record(ast.parse("class Node:\n    pass\n").body[0])
        self.assertEqual(record.fields[0].type, IrStringType())
        self.assertEqual(record.fields[1].type, IrIntType(64, signed=True))
        self.assertEqual(record.fields[2].type, IrRecordType("Node"))
        self.assertEqual(
            lowerer._record_field_types("Node"),
            (IrStringType(), IrIntType(64, signed=True), IrRecordType("Node")),
        )
        with self.assertRaises(AotError) as ctx:
            lowerer._record_field_type(IrIntType(64, signed=True), "value", ast.Pass())
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")
        with self.assertRaises(AotError) as ctx:
            lowerer._aot_type_to_ir_type(AotType("object"))
        self.assertEqual(ctx.exception.diagnostics[0].message, "Unsupported lowered type: object")

    def test_lowers_core_default_literal_and_runtime_shapes(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "from typing import Literal\n"
            "Mode = Literal['fast', 'slow']\n"
            "@dataclass(frozen=True)\n"
            "class Defaults:\n"
            "    flag: bool\n"
            "    text: str\n"
            "    empty: None\n"
            "    values: tuple[str, ...]\n"
            "    maybe: Defaults | None\n"
            "def literal(value: Literal['fast', 'slow']) -> Literal['fast', 'slow']:\n"
            "    return value\n"
            "def truth() -> bool:\n"
            "    return True\n"
            "def concat(value: str) -> str:\n"
            "    return value + 'x'\n"
            "def make() -> Defaults:\n"
            "    return Defaults()\n"
            "def raise_empty() -> None:\n"
            "    raise ValueError()\n"
        )
        module = lower_source_to_ir(source, filename="defaults.py")
        functions = {function.name: function for function in module.functions}
        self.assertEqual(functions["literal"].params[0].type, IrStringType())
        self.assertEqual(functions["truth"].return_type, IrBoolType())
        self.assertIsInstance(functions["truth"].body[0].value, IrConstBool)
        self.assertIsInstance(functions["concat"].body[0].value, IrStringConcat)
        constructed = functions["make"].body[0].value
        self.assertIsInstance(constructed, IrConstructRecord)
        self.assertIsInstance(constructed.args[0], IrConstBool)
        self.assertIsInstance(constructed.args[1], IrConstString)
        self.assertIsInstance(constructed.args[2], IrConstNone)
        self.assertIsInstance(constructed.args[3], IrTuple)
        self.assertIsInstance(constructed.args[4], IrConstNone)
        self.assertIsInstance(functions["raise_empty"].return_type, IrNoneType)
        self.assertEqual(functions["raise_empty"].body[0].message.value, "")

    def test_direct_lowerer_covers_assignment_and_global_name_edges(self) -> None:
        lowerer = _Lowerer("direct.py", {})
        names: dict[str, IrIntType] = {}
        target = ast.parse("self.value = 1\n").body[0].targets[0]
        lowerer._bind_assignment_target(target, IrIntType(64, signed=True), names)
        self.assertIn("self.value", names)
        unsupported_target = ast.parse("items[0] = 1\n").body[0].targets[0]
        with self.assertRaises(AotError) as ctx:
            lowerer._bind_assignment_target(
                unsupported_target,
                IrIntType(64, signed=True),
                names,
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")
        tree = ast.parse("left, right = (1, 2)\nname: int = 1\nclass Box:\n    pass\n")
        self.assertEqual(_collect_global_names(tree), {"name", "Box"})
        self.assertIsInstance(
            lowerer._default_expr(IrRecordType("Unknown")),
            IrConstNone,
        )
        self.assertIsInstance(
            lowerer._lower_call(
                ast.parse("''.join()\n").body[0].value,
                {},
                IrStringType(),
            ),
            IrStringJoin,
        )

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
