import ast
import unittest
from dataclasses import FrozenInstanceError

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBreak,
    IrCall,
    IrConstBool,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrEnumMember,
    IrForEach,
    IrFunction,
    IrGetField,
    IrFloatType,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRaise,
    IrRecordType,
    IrReturn,
    IrSetItem,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleType,
    IrWhile,
    analyze_source,
    lower_source_to_ir,
)
from xcc.aot.binder import _TypeBinder
from xcc.aot.lower import (
    _can_narrow_to_record,
    _collect_global_names,
    _dict_container_type_names,
    _dict_get_result_type,
    _for_each_target_type,
    _isinstance_target_names,
    _Lowerer,
    _llvm_api_call_return_type,
    _none_guard_name,
    _record_extends,
    _tuple_backed_container_element_name,
    _tuple_subscript_result_type,
)
from xcc.aot.module import parse_source
from xcc.aot.subset import check_subset
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType


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

    def test_lowers_integer_floor_division_return(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\n"
            "def div(left: int64, right: int64) -> int64:\n"
            "    return left // right\n",
            filename="div.py",
            entry="div",
        )
        function = module.functions[0]
        returned = function.body[0].value
        self.assertIsInstance(returned, IrBinary)
        self.assertEqual(returned.op, "//")
        self.assertEqual(returned.left, IrName("left", function.params[0].type))

    def test_lowers_integer_case_binary_operator_returns(self) -> None:
        cases = (("%", "%"), ("<<", "<<"), (">>", ">>"), ("|", "|"), ("&", "&"), ("^", "^"))
        for source_op, ir_op in cases:
            with self.subTest(op=source_op):
                module = lower_source_to_ir(
                    "int64 = int\n"
                    "def op(left: int64, right: int64) -> int64:\n"
                    f"    return left {source_op} right\n",
                    filename="op.py",
                    entry="op",
                )
                returned = module.functions[0].body[0].value
                self.assertIsInstance(returned, IrBinary)
                self.assertEqual(returned.op, ir_op)

    def test_lowers_try_finally_normal_path_as_ordered_branch(self) -> None:
        module = lower_source_to_ir(
            "def f() -> int:\n"
            "    value: int = 1\n"
            "    try:\n"
            "        value = 2\n"
            "    finally:\n"
            "        value = 3\n"
            "    return value\n",
            filename="try_finally.py",
            entry="f",
        )
        branch = module.functions[0].body[1]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        self.assertEqual(branch.condition, IrConstBool(True))
        self.assertEqual(
            branch.then_branch.statements,
            (
                IrAssign("value", IrConstInt(2, IrIntType(64, signed=True))),
                IrAssign("value", IrConstInt(3, IrIntType(64, signed=True))),
            ),
        )
        self.assertIsNone(branch.else_branch)

    def test_lowers_codegen_error_try_except_normal_path(self) -> None:
        module = lower_source_to_ir(
            "class CodegenError(Exception):\n"
            "    pass\n"
            "def f(value: int) -> int:\n"
            "    try:\n"
            "        return value\n"
            "    except CodegenError:\n"
            "        return 0\n",
            filename="try_codegen_error.py",
            entry="f",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        self.assertEqual(branch.condition, IrConstBool(True))
        self.assertEqual(
            branch.then_branch.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )

    def test_lowers_exception_try_except_normal_path(self) -> None:
        module = lower_source_to_ir(
            "def f(value: int) -> int:\n"
            "    try:\n"
            "        return value\n"
            "    except Exception:\n"
            "        return 0\n",
            filename="try_exception.py",
            entry="f",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        self.assertEqual(branch.condition, IrConstBool(True))
        self.assertEqual(
            branch.then_branch.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )

    def test_lowers_two_arg_integer_min_max_as_ifexp(self) -> None:
        for call, cmp_target in (("max", "__cmp_GtE"), ("min", "__cmp_LtE")):
            with self.subTest(call=call):
                module = lower_source_to_ir(
                    "int64 = int\n"
                    "def choose(left: int64, right: int64) -> int64:\n"
                    f"    return {call}(left, right)\n",
                    filename="minmax.py",
                    entry="choose",
                )
                returned = module.functions[0].body[0].value
                self.assertIsInstance(returned, IrCall)
                self.assertEqual(returned.target, "__ifexp")
                condition = returned.args[0]
                self.assertIsInstance(condition, IrCall)
                assert isinstance(condition, IrCall)
                self.assertEqual(condition.target, cmp_target)

    def test_lowers_isinstance_builtin_int_guard_for_minmax_arg(self) -> None:
        module = lower_source_to_ir(
            "def clamp(value: int | str) -> int:\n"
            "    if isinstance(value, int):\n"
            "        return max(value, 0)\n"
            "    return 0\n",
            filename="builtin_int_guard.py",
            entry="clamp",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.type, IrIntType(64, signed=True))
        self.assertEqual(
            returned.value.args[1],
            IrName("value", IrIntType(64, signed=True)),
        )

    def test_lowers_bool_and_with_isinstance_record_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "class Expr:\n"
            "    pass\n"
            "@dataclass(frozen=True)\n"
            "class UnaryExpr(Expr):\n"
            "    op: str\n"
            "def is_deref(expr: Expr) -> bool:\n"
            "    return isinstance(expr, UnaryExpr) and expr.op == '*'\n",
            filename="bool_and_narrow.py",
            entry="is_deref",
        )
        returned = module.functions[0].body[0].value
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        narrowed_compare = returned.args[1]
        self.assertIn("IrRecordType(name='UnaryExpr')", repr(narrowed_compare))

    def test_lowers_bool_and_with_not_none_record_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "def same(initializer_type: Type | None, target_type: Type) -> bool:\n"
            "    return initializer_type is not None and initializer_type.name == target_type.name\n",
            filename="bool_and_not_none_narrow.py",
            entry="same",
        )
        returned = module.functions[0].body[0].value
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        narrowed_compare = returned.args[1]
        self.assertIn("IrRecordType(name='Type')", repr(narrowed_compare))

    def test_lowers_bool_or_with_none_record_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "def mismatch(initializer_type: Type | None, target_type: Type) -> bool:\n"
            "    return initializer_type is None or initializer_type.name != target_type.name\n",
            filename="bool_or_none_narrow.py",
            entry="mismatch",
        )
        returned = module.functions[0].body[0].value
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        narrowed_compare = returned.args[1]
        self.assertIn("IrRecordType(name='Type')", repr(narrowed_compare))

    def test_lowers_if_bool_and_isinstance_narrowing_in_body(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "class Expr:\n"
            "    pass\n"
            "@dataclass(frozen=True)\n"
            "class UnaryExpr(Expr):\n"
            "    op: str\n"
            "    operand: Expr\n"
            "def operand(expr: Expr) -> Expr:\n"
            "    if isinstance(expr, UnaryExpr) and expr.op == '*':\n"
            "        return expr.operand\n"
            "    return expr\n",
            filename="if_bool_and_narrow.py",
            entry="operand",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(IrName("expr", IrRecordType("UnaryExpr")), "operand", IrRecordType("Expr")),
        )

    def test_lowers_isinstance_attribute_guard_narrowing_in_body(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "class Expr:\n"
            "    pass\n"
            "@dataclass(frozen=True)\n"
            "class Identifier(Expr):\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class CallExpr:\n"
            "    callee: Expr\n"
            "def callee_name(expr: CallExpr) -> str:\n"
            "    if isinstance(expr.callee, Identifier):\n"
            "        return expr.callee.name\n"
            "    return ''\n",
            filename="isinstance_attribute_guard.py",
            entry="callee_name",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIn("IrRecordType(name='Identifier')", repr(returned.value))

    def test_lowers_exiting_if_bool_or_none_guard_narrowing_after_body(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "    declarator_ops: tuple[str, ...]\n"
            "def width(elem_type: Type | None) -> int:\n"
            "    if elem_type is None or elem_type.declarator_ops:\n"
            "        return 0\n"
            "    if elem_type.name == 'char':\n"
            "        return 1\n"
            "    return 0\n",
            filename="if_or_none_exit_narrow.py",
            entry="width",
        )
        second_branch = module.functions[0].body[1]
        self.assertIsInstance(second_branch, IrIf)
        assert isinstance(second_branch, IrIf)
        self.assertIn("IrRecordType(name='Type')", repr(second_branch.condition))

    def test_lowers_exiting_if_negative_isinstance_guard_narrowing_after_body(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "def clamp(value: Any) -> int:\n"
            "    if not isinstance(value, int):\n"
            "        return 0\n"
            "    return max(value, 0)\n",
            filename="if_not_isinstance_exit_narrow.py",
            entry="clamp",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIn("IrIntType(bits=64, signed=True)", repr(returned.value))

    def test_lowers_exiting_if_or_none_and_negative_isinstance_narrowings(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "from typing import Any\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "def clamp(type_: Type | None, value: Any) -> int:\n"
            "    if type_ is None or not isinstance(value, int):\n"
            "        return 0\n"
            "    return max(value, 0)\n",
            filename="if_or_multiple_exit_narrow.py",
            entry="clamp",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIn("IrIntType(bits=64, signed=True)", repr(returned.value))

    def test_lowers_assert_isinstance_builtin_int_narrowing(self) -> None:
        module = lower_source_to_ir(
            "def clamp(value: int | str) -> int:\n"
            "    assert isinstance(value, int)\n"
            "    return max(value, 0)\n",
            filename="assert_builtin_int.py",
            entry="clamp",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(
            returned.value.args[1],
            IrName("value", IrIntType(64, signed=True)),
        )

    def test_lowers_dict_items_for_tuple_for_target_types(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    values: dict[str, int]\n"
            "def total(box: Box) -> int:\n"
            "    result: int = 0\n"
            "    for key, value in box.values.items():\n"
            "        result = result + value\n"
            "    return result\n",
            filename="dict_items.py",
            entry="total",
        )
        loop = module.functions[0].body[1]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertEqual(loop.target, "(key, value)")
        self.assertIn("value', type=IrIntType", repr(loop.body))

    def test_lowers_zip_for_tuple_for_target_types(self) -> None:
        module = lower_source_to_ir(
            "def total(names: list[str], values: list[int]) -> int:\n"
            "    result: int = 0\n"
            "    for name, value in zip(names, values, strict=True):\n"
            "        result = result + value\n"
            "    return result\n",
            filename="zip_loop.py",
            entry="total",
        )
        loop = module.functions[0].body[1]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertIn("target='__zip'", repr(loop.iterable))
        self.assertIn("value', type=IrIntType", repr(loop.body))

    def test_lowers_string_split_as_tuple_of_strings(self) -> None:
        module = lower_source_to_ir(
            "def parts(value: str) -> tuple[str, ...]:\n"
            "    return value.split('.')\n",
            filename="split.py",
            entry="parts",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__str_split",
                (IrName("value", IrStringType()), IrConstString(".")),
                IrTupleType((IrStringType(),)),
            ),
        )

    def test_lowers_string_find_as_int(self) -> None:
        default_start = lower_source_to_ir(
            "def quote(value: str) -> int:\n"
            "    return value.find('\"')\n",
            filename="find.py",
            entry="quote",
        )
        returned = default_start.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__str_find",
                (
                    IrName("value", IrStringType()),
                    IrConstString('"'),
                    IrConstInt(0, IrIntType(64, signed=True)),
                ),
                IrIntType(64, signed=True),
            ),
        )
        explicit_start = lower_source_to_ir(
            "def quote(value: str, start: int) -> int:\n"
            "    return value.find('\"', start)\n",
            filename="find_start.py",
            entry="quote",
        )
        returned = explicit_start.functions[0].body[0].value
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        self.assertEqual(returned.target, "__str_find")
        self.assertEqual(returned.args[2], IrName("start", IrIntType(64, signed=True)))

    def test_lowers_chr_builtin_as_string(self) -> None:
        module = lower_source_to_ir(
            "def decoded(text: str) -> str:\n"
            "    return chr(int(text, 16))\n",
            filename="chr_builtin.py",
            entry="decoded",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__chr",
                (
                    IrCall(
                        "__int_parse",
                        (
                            IrName("text", IrStringType()),
                            IrConstInt(16, IrIntType(64, signed=True)),
                        ),
                        IrIntType(64, signed=True),
                    ),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_float_builtin_and_fromhex_as_float(self) -> None:
        parsed = lower_source_to_ir(
            "def parsed(value: int) -> float:\n"
            "    return float(value)\n",
            filename="float_builtin.py",
            entry="parsed",
        )
        returned = parsed.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__float",
                (IrName("value", IrIntType(64, signed=True)),),
                IrFloatType(),
            ),
        )
        fromhex = lower_source_to_ir(
            "def parsed(text: str) -> float:\n"
            "    return float.fromhex(text)\n",
            filename="float_fromhex.py",
            entry="parsed",
        )
        returned = fromhex.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall("__float_fromhex", (IrName("text", IrStringType()),), IrFloatType()),
        )

    def test_lowers_staticmethod_called_through_self_without_receiver_arg(self) -> None:
        module = lower_source_to_ir(
            "class Gen:\n"
            "    @staticmethod\n"
            "    def encode(body: str, width: int) -> str:\n"
            "        return body\n"
            "    def use(self, body: str) -> str:\n"
            "        return self.encode(body, 2)\n",
            filename="staticmethod_call.py",
            entry="Gen.use",
        )
        function = next(function for function in module.functions if function.name == "Gen.use")
        returned = function.body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "Gen.encode",
                (
                    IrName("body", IrStringType()),
                    IrConstInt(2, IrIntType(64, signed=True)),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_ifexp_not_none_attribute_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Symbol:\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class Gen:\n"
            "    sym: Symbol | None\n"
            "    def get(self) -> str:\n"
            "        return self.sym.name if self.sym is not None else ''\n",
            filename="ifexp_not_none_attr.py",
            entry="Gen.get",
        )
        function = next(function for function in module.functions if function.name == "Gen.get")
        returned = function.body[0].value
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        self.assertIn("IrRecordType(name='Symbol')", repr(returned.args[1]))

    def test_lowers_common_field_access_on_record_union(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Left:\n"
            "    value: int\n"
            "@dataclass(frozen=True)\n"
            "class Right:\n"
            "    value: int\n"
            "def read(expr: Left | Right) -> int:\n"
            "    return expr.value\n",
            filename="union_common_field.py",
            entry="read",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrGetField(
                IrName("expr", IrRecordType("Left | Right")),
                "value",
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_nested_field_receiver_without_outer_expected_type(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Item:\n"
            "    designators: list[str]\n"
            "@dataclass(frozen=True)\n"
            "class Init:\n"
            "    items: list[Item]\n"
            "def empty(init: Init) -> bool:\n"
            "    return not init.items[0].designators\n",
            filename="nested_field.py",
            entry="empty",
        )
        returned = module.functions[0].body[0].value
        self.assertIn("field='designators'", repr(returned))
        self.assertIn("IrRecordType(name='Item')", repr(returned))

    def test_infers_subscript_assignment_item_type(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Item:\n"
            "    names: list[str]\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    items: list[Item]\n"
            "def has_names(box: Box) -> bool:\n"
            "    item = box.items[0]\n"
            "    return bool(item.names)\n",
            filename="subscript_assignment.py",
            entry="has_names",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value.type, IrRecordType("Item"))

    def test_lowers_top_level_optional_tuple_return(self) -> None:
        module = lower_source_to_ir(
            "def maybe(flag: bool) -> tuple[int, str] | None:\n"
            "    if flag:\n"
            "        return 0, 'x'\n"
            "    return None\n",
            filename="optional_tuple.py",
            entry="maybe",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrTuple(
                (
                    IrConstInt(0, IrIntType(64, signed=True)),
                    IrConstString("x"),
                ),
                IrTupleType((IrIntType(64, signed=True), IrStringType())),
            ),
        )

    def test_lowers_top_level_optional_tuple_backed_container(self) -> None:
        module = lower_source_to_ir(
            "def second(values: list[tuple[int, str]] | None) -> str:\n"
            "    if values is None:\n"
            "        return ''\n"
            "    return values[0][1]\n",
            filename="optional_list.py",
            entry="second",
        )
        self.assertEqual(
            module.functions[0].params[0].type,
            IrTupleType(
                (
                    IrTupleType(
                        (
                            IrIntType(64, signed=True),
                            IrStringType(),
                        )
                    ),
                )
            ),
        )
        returned = module.functions[0].body[1].value
        self.assertEqual(returned.type, IrStringType())

    def test_infers_optional_tuple_backed_method_call_assignment_type(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Member:\n"
            "    type_: str\n"
            "class Gen:\n"
            "    def member_path(self) -> list[tuple[str, int, Member]] | None:\n"
            "        return None\n"
            "    def use(self) -> str:\n"
            "        path = self.member_path()\n"
            "        if path is None:\n"
            "            return ''\n"
            "        return path[-1][2].type_\n",
            filename="method_optional_container.py",
            entry="Gen.use",
        )
        function = next(function for function in module.functions if function.name == "Gen.use")
        returned = function.body[2].value
        self.assertEqual(returned.type, IrStringType())

    def test_lowers_list_literal_with_tuple_backed_expected_item_type(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Member:\n"
            "    type_: str\n"
            "def consume(path: list[tuple[str, int, Member]]) -> int:\n"
            "    return 0\n"
            "def use(name: str, first: Member) -> int:\n"
            "    return consume([(name, 0, first)])\n",
            filename="list_literal_tuple_item.py",
            entry="use",
        )
        function = next(function for function in module.functions if function.name == "use")
        returned = function.body[0].value
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        self.assertEqual(
            returned.args[0].type,
            IrTupleType(
                (
                    IrTupleType(
                        (
                            IrStringType(),
                            IrIntType(64, signed=True),
                            IrRecordType("Member"),
                        )
                    ),
                )
            ),
        )

    def test_lowers_listcomp_and_append_with_tuple_backed_item_type(self) -> None:
        module = lower_source_to_ir(
            "def values(body: str) -> list[int]:\n"
            "    result = [1 for ch in body]\n"
            "    result.append(0)\n"
            "    return result\n",
            filename="listcomp_append.py",
            entry="values",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value.type, IrTupleType((IrIntType(64, signed=True),)))
        append = module.functions[0].body[1].value
        self.assertIsInstance(append, IrCall)
        assert isinstance(append, IrCall)
        self.assertEqual(append.args[1], IrConstInt(0, IrIntType(64, signed=True)))

    def test_lowers_empty_container_constructor_with_tuple_backed_expected_type(self) -> None:
        module = lower_source_to_ir(
            "def make_seen() -> set[str]:\n"
            "    seen: set[str] = set()\n"
            "    return seen\n",
            filename="empty_set_constructor.py",
            entry="make_seen",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value, IrTuple((), IrTupleType((IrStringType(),))))

    def test_lowers_set_add_with_tuple_backed_item_type(self) -> None:
        module = lower_source_to_ir(
            "def add_name(name: str) -> set[str]:\n"
            "    seen: set[str] = set()\n"
            "    seen.add(name)\n"
            "    return seen\n",
            filename="set_add.py",
            entry="add_name",
        )
        add = module.functions[0].body[1].value
        self.assertIsInstance(add, IrCall)
        assert isinstance(add, IrCall)
        self.assertEqual(add.args[1], IrName("name", IrStringType()))

    def test_lowers_tuple_constructor_as_tuple_backed_identity(self) -> None:
        module = lower_source_to_ir(
            "def freeze(values: list[int]) -> tuple[int, ...]:\n"
            "    return tuple(values)\n",
            filename="tuple_constructor.py",
            entry="freeze",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(returned, IrName("values", IrTupleType((IrIntType(64, signed=True),))))

    def test_lowers_range_arguments_as_int_tuple_iterable(self) -> None:
        module = lower_source_to_ir(
            "def sum_to(length: int) -> int:\n"
            "    total = 0\n"
            "    for index in range(max(length, 0)):\n"
            "        total += index\n"
            "    return total\n",
            filename="range_max.py",
            entry="sum_to",
        )
        loop = module.functions[0].body[1]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertEqual(loop.iterable.type, IrTupleType((IrIntType(64, signed=True),)))
        self.assertEqual(loop.target, "index")

    def test_infers_minmax_assignment_type_independent_of_function_return(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "def positive(value: Any) -> bool:\n"
            "    if not isinstance(value, int):\n"
            "        return False\n"
            "    length = max(value, 0)\n"
            "    return length > 0\n",
            filename="minmax_assignment.py",
            entry="positive",
        )
        assigned = module.functions[0].body[1]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value.type, IrIntType(64, signed=True))

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
        self.assertEqual(record.fields[0].type, IrTupleType((IrStringType(), IrIntType(64, True))))
        self.assertEqual(record.fields[1].type, IrTupleType((IrStringType(),)))

    def test_lowers_for_target_from_homogeneous_container_annotation(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class FunctionDef:\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class Unit:\n"
            "    functions: list[FunctionDef]\n"
            "def first_name(unit: Unit) -> str:\n"
            "    for func in unit.functions:\n"
            "        return func.name\n"
            "    return ''\n",
            filename="container_for.py",
        )
        function = module.functions[0]
        loop = function.body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        returned = loop.body.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        value = returned.value
        self.assertIsInstance(value, IrGetField)
        assert isinstance(value, IrGetField)
        self.assertEqual(value.field, "name")
        self.assertEqual(value.value.type, IrRecordType("FunctionDef"))

    def test_lowers_enumerate_for_target_from_homogeneous_container_annotation(self) -> None:
        module = lower_source_to_ir(
            "def first_index(names: list[str]) -> int:\n"
            "    for index, name in enumerate(names):\n"
            "        return index\n"
            "    return 0\n",
            filename="enumerate_for.py",
        )
        function = module.functions[0]
        loop = function.body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertEqual(loop.target, "(index, name)")
        self.assertIsInstance(loop.iterable, IrCall)
        assert isinstance(loop.iterable, IrCall)
        self.assertEqual(loop.iterable.target, "__enumerate")
        self.assertEqual(loop.iterable.type, IrTupleType((IrIntType(64, True), IrStringType())))
        returned = loop.body.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("index", IrIntType(64, True)))

        skipped_item = lower_source_to_ir(
            "def first_index(names: list[str]) -> int:\n"
            "    for index, _ in enumerate(names):\n"
            "        return index\n"
            "    return 0\n",
            filename="enumerate_skip_item.py",
        )
        skipped_loop = skipped_item.functions[0].body[0]
        self.assertIsInstance(skipped_loop, IrForEach)
        assert isinstance(skipped_loop, IrForEach)
        self.assertEqual(skipped_loop.target, "(index, _)")

    def test_lowers_llvm_api_receiver_call(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def make_function_type(ret_t: int, param_ts: int, n: int, variadic: bool) -> int:\n"
            "    c = llvm()\n"
            "    return c.FunctionType(ret_t, param_ts, n, variadic)\n",
            filename="llvm_api_call.py",
        )
        function = module.functions[0]
        assigned = function.body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.target, "c")
        self.assertEqual(assigned.value, IrCall("__llvm_api", (), IrRecordType("LLVMApi")))
        returned = function.body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_FunctionType",
                (
                    IrName("ret_t", IrIntType(64, signed=True)),
                    IrName("param_ts", IrIntType(64, signed=True)),
                    IrName("n", IrIntType(64, signed=True)),
                    IrName("variadic", IrBoolType()),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_str_encode_as_c_string_identity_for_llvm_api_call(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def lookup(module: int, name: str) -> int:\n"
            "    c = llvm()\n"
            "    return c.GetNamedFunction(module, name.encode())\n",
            filename="llvm_api_encode.py",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_GetNamedFunction",
                (
                    IrName("module", IrIntType(64, signed=True)),
                    IrName("name", IrStringType()),
                ),
                IrIntType(64, signed=True),
            ),
        )

        encoded = lower_source_to_ir(
            "def encoded(name: str) -> str:\n"
            "    return name.encode('utf-8')\n",
            filename="str_encode_arg.py",
        )
        self.assertEqual(encoded.functions[0].body[0].value, IrName("name", IrStringType()))

    def test_lowers_bytes_literal_as_c_string_for_llvm_api_call(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def append_block(fn: int) -> int:\n"
            "    c = llvm()\n"
            "    return c.AppendBasicBlock(fn, b'entry')\n",
            filename="llvm_api_bytes.py",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_AppendBasicBlock",
                (IrName("fn", IrIntType(64, signed=True)), IrConstString("entry")),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_float_literal_for_llvm_api_call(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def zero_value(type_ref: int) -> int:\n"
            "    c = llvm()\n"
            "    return c.ConstReal(type_ref, 0.0)\n",
            filename="llvm_api_float.py",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_ConstReal",
                (IrName("type_ref", IrIntType(64, signed=True)), IrConstFloat(0.0)),
                IrIntType(64, signed=True),
            ),
        )
        self.assertEqual(IrConstFloat(0.0).type, IrFloatType())

    def test_lowers_negative_int_literal_subscript_index(self) -> None:
        module = lower_source_to_ir(
            "def last(values: tuple[str, ...]) -> str:\n"
            "    return values[-1]\n",
            filename="negative_index.py",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__getitem",
                (
                    IrName("values", IrTupleType((IrStringType(),))),
                    IrConstInt(-1, IrIntType(64, signed=True)),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_tuple_assignment_from_homogeneous_tuple_subscript(self) -> None:
        module = lower_source_to_ir(
            "def first_kind(ops: tuple[TypeOp, ...]) -> str:\n"
            "    kind, _ = ops[0]\n"
            "    return kind\n",
            filename="tuple_assign_subscript.py",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrCall(
                "__getitem",
                (
                    IrName(
                        "ops",
                        IrTupleType((IrTupleType((IrStringType(), IrRecordType("object"))),)),
                    ),
                    IrConstInt(0, IrIntType(64, signed=True)),
                ),
                IrTupleType((IrStringType(), IrRecordType("object"))),
            ),
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("kind", IrStringType()))

    def test_lowers_tuple_assignment_from_object_value_with_object_slots(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "def first(packed: Any) -> Any:\n"
            "    left, _ = packed\n"
            "    return left\n",
            filename="tuple_assign_object.py",
        )
        assigned = module.functions[0].body[0]
        self.assertEqual(
            assigned,
            IrAssign("(left, _)", IrName("packed", IrRecordType("object"))),
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("left", IrRecordType("object")))

    def test_lowers_reversed_preserving_tuple_element_type(self) -> None:
        module = lower_source_to_ir(
            "def first_kind(ops: tuple[TypeOp, ...]) -> str:\n"
            "    for kind, value in reversed(ops):\n"
            "        return kind\n"
            "    return ''\n",
            filename="reversed_tuple_type.py",
        )
        op_type = IrTupleType((IrStringType(), IrRecordType("object")))
        ops_type = IrTupleType((op_type,))
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertEqual(loop.target, "(kind, value)")
        self.assertEqual(loop.iterable, IrCall("reversed", (IrName("ops", ops_type),), ops_type))
        returned = loop.body.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("kind", IrStringType()))

    def test_lowerer_nested_tuple_subscript_prefers_container_element_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        item_type = IrTupleType((IrStringType(), int64, IrRecordType("object")))
        path_type = IrTupleType((item_type,))
        lowerer = _Lowerer("nested_subscript.py", {})
        expr = ast.parse("path[0][1]", mode="eval").body

        lowered = lowerer._lower_expr(expr, {"path": path_type}, int64)

        self.assertEqual(
            lowered,
            IrCall(
                "__getitem",
                (
                    IrCall(
                        "__getitem",
                        (IrName("path", path_type), IrConstInt(0, int64)),
                        item_type,
                    ),
                    IrConstInt(1, int64),
                ),
                int64,
            ),
        )

        unknown_index = ast.parse("item[index]", mode="eval").body
        unknown_lowered = lowerer._lower_expr(
            unknown_index,
            {"item": item_type, "index": int64},
            int64,
        )
        self.assertEqual(
            unknown_lowered,
            IrCall(
                "__getitem",
                (IrName("item", item_type), IrName("index", int64)),
                int64,
            ),
        )

    def test_lowers_unary_int_plus_and_minus_expressions(self) -> None:
        negated = lower_source_to_ir(
            "def negate(value: int) -> int:\n"
            "    return -value\n",
            filename="unary_minus.py",
        )
        self.assertEqual(
            negated.functions[0].body[0].value,
            IrBinary(
                "-",
                IrConstInt(0, IrIntType(64, signed=True)),
                IrName("value", IrIntType(64, signed=True)),
                IrIntType(64, signed=True),
            ),
        )

        positive = lower_source_to_ir(
            "def positive(value: int) -> int:\n"
            "    return +value\n",
            filename="unary_plus.py",
        )
        self.assertEqual(
            positive.functions[0].body[0].value,
            IrName("value", IrIntType(64, signed=True)),
        )

    def test_infers_negative_int_literal_assignment_type(self) -> None:
        module = lower_source_to_ir(
            "def f() -> tuple[int, ...]:\n"
            "    value = -1\n"
            "    return (value,)\n",
            filename="negative_assignment.py",
            entry="f",
        )
        self.assertEqual(
            module.functions[0].body[0],
            IrAssign("value", IrConstInt(-1, IrIntType(64, signed=True))),
        )

    def test_lowers_unary_int_invert_expression(self) -> None:
        module = lower_source_to_ir(
            "def invert(value: int) -> int:\n"
            "    return ~value\n",
            filename="unary_invert.py",
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0].value,
            IrBinary(
                "-",
                IrConstInt(-1, int64),
                IrName("value", int64),
                int64,
            ),
        )

    def test_lowers_tuple_backed_pop_call_statement(self) -> None:
        module = lower_source_to_ir(
            "def drop(values: list[str]) -> None:\n"
            "    values.pop()\n",
            filename="tuple_pop.py",
        )
        statement = module.functions[0].body[0]
        self.assertEqual(
            statement,
            IrAssign(
                "__expr",
                IrCall(
                    "values.pop",
                    (IrName("values", IrTupleType((IrStringType(),))),),
                    IrNoneType(),
                ),
            ),
        )

    def test_lowers_pass_statement_as_noop(self) -> None:
        module = lower_source_to_ir(
            "def skip() -> None:\n"
            "    pass\n",
            filename="pass.py",
        )
        self.assertEqual(module.functions[0].body[0], IrAssign("__pass", IrConstNone()))

    def test_lowers_dict_get_and_none_guard_narrows_optional_record(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class FunctionSymbol:\n"
            "    return_type: Type\n"
            "@dataclass(frozen=True)\n"
            "class SemaUnit:\n"
            "    functions: dict[str, FunctionSymbol]\n"
            "def return_name(sema: SemaUnit, name: str) -> str:\n"
            "    func_sym = sema.functions.get(name)\n"
            "    if func_sym is None:\n"
            "        return ''\n"
            "    return func_sym.return_type.name\n",
            filename="dict_get_optional.py",
        )
        function = module.functions[0]
        assigned = function.body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__dict_get")
        self.assertEqual(assigned.value.type, IrRecordType("FunctionSymbol | None"))
        returned = function.body[2]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        name_field = returned.value
        self.assertIsInstance(name_field, IrGetField)
        assert isinstance(name_field, IrGetField)
        return_type_field = name_field.value
        self.assertIsInstance(return_type_field, IrGetField)
        assert isinstance(return_type_field, IrGetField)
        self.assertEqual(return_type_field.value, IrName("func_sym", IrRecordType("FunctionSymbol")))

    def test_lowers_tuple_backed_dict_subscript_as_dict_get(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Cache:\n"
            "    values: dict[str, int]\n"
            "def lookup(cache: Cache, key: str) -> int:\n"
            "    return cache.values[key]\n",
            filename="dict_subscript.py",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__dict_get",
                (
                    IrGetField(
                        IrName("cache", IrRecordType("Cache")),
                        "values",
                        IrTupleType((IrStringType(), IrIntType(64, signed=True))),
                    ),
                    IrName("key", IrStringType()),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_isinstance_guarded_ifexp_record_field(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class VarSymbol:\n"
            "    type_: Type\n"
            "@dataclass(frozen=True)\n"
            "class OtherSymbol:\n"
            "    type_: Type\n"
            "def pick_type(symbol: VarSymbol | OtherSymbol, fallback: Type) -> Type:\n"
            "    return symbol.type_ if isinstance(symbol, VarSymbol) else fallback\n",
            filename="isinstance_ifexp.py",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__ifexp",
                (
                    IrCall(
                        "isinstance",
                        (
                            IrName("symbol", IrRecordType("VarSymbol | OtherSymbol")),
                            IrName("VarSymbol", IrBoolType()),
                        ),
                        IrBoolType(),
                    ),
                    IrGetField(
                        IrName("symbol", IrRecordType("VarSymbol")),
                        "type_",
                        IrRecordType("Type"),
                    ),
                    IrName("fallback", IrRecordType("Type")),
                ),
                IrRecordType("Type"),
            ),
        )

    def test_lowers_isinstance_guarded_if_statement_record_field(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "class Stmt:\n"
            "    pass\n"
            "@dataclass(frozen=True)\n"
            "class CompoundStmt(Stmt):\n"
            "    statements: list[str]\n"
            "@dataclass(frozen=True)\n"
            "class ReturnStmt(Stmt):\n"
            "    value: str\n"
            "def first(stmt: Stmt) -> str:\n"
            "    if isinstance(stmt, CompoundStmt):\n"
            "        return stmt.statements[0]\n"
            "    return ''\n",
            filename="isinstance_if.py",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__getitem",
                (
                    IrGetField(
                        IrName("stmt", IrRecordType("CompoundStmt")),
                        "statements",
                        IrTupleType((IrStringType(),)),
                    ),
                    IrConstInt(0, IrIntType(64, signed=True)),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_isinstance_tuple_guarded_common_record_field(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "class Stmt:\n"
            "    pass\n"
            "@dataclass(frozen=True)\n"
            "class WhileStmt(Stmt):\n"
            "    body: list[str]\n"
            "@dataclass(frozen=True)\n"
            "class LabelStmt(Stmt):\n"
            "    body: list[str]\n"
            "@dataclass(frozen=True)\n"
            "class ReturnStmt(Stmt):\n"
            "    value: str\n"
            "def body_len(stmt: Stmt) -> int:\n"
            "    if isinstance(stmt, (WhileStmt, LabelStmt)):\n"
            "        return len(stmt.body)\n"
            "    return 0\n",
            filename="isinstance_tuple_if.py",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "len",
                (
                    IrGetField(
                        IrName("stmt", IrRecordType("WhileStmt | LabelStmt")),
                        "body",
                        IrTupleType((IrStringType(),)),
                    ),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_for_tuple_target_with_underscore_skip(self) -> None:
        module = lower_source_to_ir(
            "def second(pairs: list[tuple[int, int]]) -> int:\n"
            "    for _, value in pairs:\n"
            "        return value\n"
            "    return 0\n",
            filename="for_tuple_underscore.py",
        )
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        returned = loop.body.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("value", IrIntType(64, signed=True)))

    def test_rejects_for_tuple_target_shape_and_non_name_element(self) -> None:
        cases = (
            (
                "shape",
                "def bad(pairs: list[tuple[int, int, int]]) -> None:\n"
                "    for left, right in pairs:\n"
                "        pass\n",
            ),
            (
                "non_name",
                "from dataclasses import dataclass\n"
                "@dataclass(frozen=True)\n"
                "class Box:\n"
                "    x: int\n"
                "def bad(pairs: list[tuple[int, int]], box: Box) -> None:\n"
                "    for box.x, right in pairs:\n"
                "        pass\n",
            ),
        )
        for name, source in cases:
            with self.subTest(name=name):
                with self.assertRaises(AotError):
                    lower_source_to_ir(source, filename=f"for_tuple_{name}.py")

    def test_lowers_truthy_optional_instance_field_guard(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class FunctionSymbol:\n"
            "    locals: dict[str, int]\n"
            "class Owner:\n"
            "    def __init__(self, sym: FunctionSymbol | None) -> None:\n"
            "        self._func_sym = sym\n"
            "    def local_count(self) -> int:\n"
            "        if self._func_sym:\n"
            "            return len(self._func_sym.locals)\n"
            "        return 0\n",
            filename="truthy_optional_field.py",
            include_records={"Owner", "FunctionSymbol"},
            include_functions={"Owner.local_count"},
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "len",
                (
                    IrGetField(
                        IrGetField(
                            IrName("self", IrRecordType("Owner")),
                            "_func_sym",
                            IrRecordType("FunctionSymbol"),
                        ),
                        "locals",
                        IrTupleType((IrStringType(), IrIntType(64, signed=True))),
                    ),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_not_none_optional_instance_field_guard(self) -> None:
        module = lower_source_to_ir(
            "class Scope:\n"
            "    def lookup(self, name: str) -> int:\n"
            "        return 1\n"
            "class Owner:\n"
            "    def __init__(self, scope: Scope | None) -> None:\n"
            "        self.scope = scope\n"
            "    def read(self) -> int:\n"
            "        if self.scope is not None:\n"
            "            return self.scope.lookup('x')\n"
            "        return 0\n",
            filename="not_none_optional_field.py",
            include_records={"Owner", "Scope"},
            include_functions={"Owner.read"},
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "Scope.lookup",
                (
                    IrGetField(
                        IrName("self", IrRecordType("Owner")),
                        "scope",
                        IrRecordType("Scope"),
                    ),
                    IrConstString("x"),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_isinstance_after_optional_assignment_without_else(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class VarSymbol:\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class EnumConstSymbol:\n"
            "    value: int\n"
            "class Scope:\n"
            "    def lookup(self, name: str) -> VarSymbol | EnumConstSymbol | None:\n"
            "        return None\n"
            "class Owner:\n"
            "    def __init__(self, scope: Scope | None) -> None:\n"
            "        self.scope = scope\n"
            "    def read(self, name: str) -> int:\n"
            "        sym = None\n"
            "        if self.scope is not None:\n"
            "            sym = self.scope.lookup(name)\n"
            "        if isinstance(sym, EnumConstSymbol):\n"
            "            return sym.value\n"
            "        return 0\n",
            filename="optional_assignment_no_else.py",
            include_records={"Owner", "Scope", "VarSymbol", "EnumConstSymbol"},
            include_functions={"Owner.read"},
        )
        branch = module.functions[0].body[2]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrName("sym", IrRecordType("EnumConstSymbol")),
                "value",
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_with_extra_cross_module_method_signature(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class VarSymbol:\n"
            "    name: str\n"
            "@dataclass(frozen=True)\n"
            "class EnumConstSymbol:\n"
            "    value: int\n"
            "class Scope:\n"
            "    pass\n"
            "class Owner:\n"
            "    def __init__(self, scope: Scope) -> None:\n"
            "        self.scope = scope\n"
            "    def read(self, name: str) -> int:\n"
            "        sym = None\n"
            "        sym = self.scope.lookup(name)\n"
            "        if isinstance(sym, EnumConstSymbol):\n"
            "            return sym.value\n"
            "        return 0\n",
            filename="extra_method_signature.py",
            include_records={"Owner", "Scope", "VarSymbol", "EnumConstSymbol"},
            include_functions={"Owner.read"},
            extra_functions={
                "Scope.lookup": AotFunctionInfo(
                    "Scope.lookup",
                    (("self", "Scope"), ("name", "str")),
                    AotType("VarSymbol | EnumConstSymbol | None"),
                )
            },
        )
        branch = module.functions[0].body[2]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrName("sym", IrRecordType("EnumConstSymbol")),
                "value",
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_empty_dict_literal_as_tuple_backed_container(self) -> None:
        module = lower_source_to_ir(
            "def empty() -> dict[str, int]:\n"
            "    values: dict[str, int] = {}\n"
            "    return values\n",
            filename="empty_dict_literal.py",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrTuple((), IrTupleType((IrStringType(), IrIntType(64, signed=True)))),
        )

    def test_lowers_subscript_assignment_statement(self) -> None:
        module = lower_source_to_ir(
            "def store(values: list[str], index: int, item: str) -> None:\n"
            "    values[index] = item\n",
            filename="subscript_assign.py",
        )
        statement = module.functions[0].body[0]
        self.assertIsInstance(statement, IrSetItem)
        assert isinstance(statement, IrSetItem)
        self.assertEqual(statement.target, IrName("values", IrTupleType((IrStringType(),))))
        self.assertEqual(statement.index, IrName("index", IrIntType(64, signed=True)))
        self.assertEqual(statement.value, IrName("item", IrStringType()))

    def test_tuple_backed_container_element_name_edges(self) -> None:
        self.assertIsNone(_tuple_backed_container_element_name("Callable[[str], bool]"))
        self.assertIsNone(_tuple_backed_container_element_name("dict[str, int]"))
        self.assertIsNone(_tuple_backed_container_element_name("tuple[]"))
        self.assertEqual(
            _tuple_backed_container_element_name("list['FunctionDef']"),
            "FunctionDef",
        )
        self.assertEqual(
            _tuple_backed_container_element_name("tuple[list[str], ...]"),
            "list[str]",
        )
        self.assertIsNone(_dict_container_type_names("dict[str]"))
        self.assertEqual(
            _dict_container_type_names("dict[str, list[int]]"),
            ("str", "list[int]"),
        )
        self.assertEqual(
            _dict_get_result_type(IrRecordType("FunctionSymbol | None")),
            IrRecordType("FunctionSymbol | None"),
        )
        self.assertEqual(
            _dict_get_result_type(IrIntType(64, signed=True)),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _none_guard_name(ast.parse("None is value").body[0].value),
            "value",
        )
        self.assertIsNone(_none_guard_name(ast.parse("None is 1").body[0].value))

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

    def test_lowers_while_loop_statement(self) -> None:
        module = lower_source_to_ir(
            "def spin(limit: int) -> int:\n"
            "    value: int = 0\n"
            "    while value < limit:\n"
            "        value = value + 1\n"
            "    return value\n",
            filename="while_loop.py",
        )
        function = module.functions[0]
        self.assertIsInstance(function.body[1], IrWhile)
        self.assertIn("__cmp_Lt", repr(function.body[1].condition))
        self.assertIn("value", repr(function.body[1].body))

    def test_lowers_loop_break_and_continue_statements(self) -> None:
        module = lower_source_to_ir(
            "def spin(limit: int) -> int:\n"
            "    value: int = 0\n"
            "    while value < limit:\n"
            "        value = value + 1\n"
            "        if value < limit:\n"
            "            continue\n"
            "        break\n"
            "    return value\n",
            filename="loop_control.py",
        )
        loop = module.functions[0].body[1]
        self.assertIsInstance(loop.body.statements[1].then_branch.statements[0], IrContinue)
        self.assertIsInstance(loop.body.statements[2], IrBreak)

    def test_lowers_augmented_assignment_statements(self) -> None:
        module = lower_source_to_ir(
            "def inc(value: int) -> int:\n"
            "    value += 1\n"
            "    return value\n"
            "def dec(value: int) -> int:\n"
            "    value -= 1\n"
            "    return value\n"
            "def scale(value: int) -> int:\n"
            "    value *= 2\n"
            "    return value\n",
            filename="augassign.py",
        )
        int64 = IrIntType(64, signed=True)
        expected = (
            ("inc", "+", 1),
            ("dec", "-", 1),
            ("scale", "*", 2),
        )
        for function, (_, op, constant) in zip(module.functions, expected, strict=True):
            self.assertEqual(
                function.body[0],
                IrAssign(
                    "value",
                    IrBinary(
                        op,
                        IrName("value", int64),
                        IrConstInt(constant, int64),
                        int64,
                    ),
                ),
            )

    def test_lowers_augmented_assignment_to_instance_field(self) -> None:
        module = lower_source_to_ir(
            "class Counter:\n"
            "    def __init__(self) -> None:\n"
            "        self.count = 0\n"
            "    def bump(self) -> int:\n"
            "        self.count += 1\n"
            "        return self.count\n",
            filename="augassign_field.py",
            include_records={"Counter"},
            include_functions={"Counter.bump"},
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0],
            IrAssign(
                "self.count",
                IrBinary(
                    "+",
                    IrGetField(IrName("self", IrRecordType("Counter")), "count", int64),
                    IrConstInt(1, int64),
                    int64,
                ),
            ),
        )

    def test_lowers_assignment_value_using_existing_target_type(self) -> None:
        module = lower_source_to_ir(
            "class Cursor:\n"
            "    def __init__(self) -> None:\n"
            "        self.column = 0\n"
            "    def reset(self) -> str:\n"
            "        self.column = 1\n"
            "        return ''\n"
            "def local() -> str:\n"
            "    count: int = 0\n"
            "    count = 1\n"
            "    return ''\n",
            filename="assignment_context.py",
            include_records={"Cursor"},
            include_functions={"Cursor.reset", "local"},
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(module.functions[0].body[0], IrAssign("self.column", IrConstInt(1, int64)))
        self.assertEqual(module.functions[1].body[1], IrAssign("count", IrConstInt(1, int64)))

    def test_lowers_assignment_value_using_literal_ifexp_type(self) -> None:
        module = lower_source_to_ir(
            "def choose(kind: str) -> None:\n"
            "    count = 4 if kind == 'u' else 8\n",
            filename="assignment_ifexp.py",
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0],
            IrAssign(
                "count",
                IrCall(
                    "__ifexp",
                    (
                        IrCall(
                            "__cmp_Eq",
                            (IrName("kind", IrStringType()), IrConstString("u")),
                            IrBoolType(),
                        ),
                        IrConstInt(4, int64),
                        IrConstInt(8, int64),
                    ),
                    int64,
                ),
            ),
        )

        inferred = lower_source_to_ir(
            "def infer() -> None:\n"
            "    flag = True\n"
            "    empty = None\n"
            "    text = 'x'\n"
            "    alias = text\n"
            "    values = []\n",
            filename="assignment_literals.py",
        )
        self.assertEqual(inferred.functions[0].body[0], IrAssign("flag", IrConstBool(True)))
        self.assertEqual(inferred.functions[0].body[1], IrAssign("empty", IrConstNone()))
        self.assertEqual(inferred.functions[0].body[2], IrAssign("text", IrConstString("x")))
        self.assertEqual(inferred.functions[0].body[3], IrAssign("alias", IrName("text", IrStringType())))
        self.assertEqual(inferred.functions[0].body[4], IrAssign("values", IrTuple((), IrTupleType(()))))

    def test_lowers_string_startswith_method_call(self) -> None:
        module = lower_source_to_ir(
            "def check(text: str, prefix: str, start: int) -> bool:\n"
            "    return text.startswith(prefix, start)\n",
            filename="startswith.py",
        )
        returned = module.functions[0].body[0].value
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            returned,
            IrCall(
                "__str_startswith",
                (
                    IrName("text", IrStringType()),
                    IrName("prefix", IrStringType()),
                    IrName("start", int64),
                ),
                IrBoolType(),
            ),
        )

        default_start = lower_source_to_ir(
            "def check(text: str, prefix: str) -> bool:\n"
            "    return text.startswith(prefix)\n",
            filename="startswith_default.py",
        )
        returned = default_start.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__str_startswith",
                (
                    IrName("text", IrStringType()),
                    IrName("prefix", IrStringType()),
                    IrConstInt(0, int64),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_string_endswith_method_call(self) -> None:
        module = lower_source_to_ir(
            "def check(text: str, suffix: str) -> bool:\n"
            "    return text.endswith(suffix)\n",
            filename="endswith.py",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__str_endswith",
                (IrName("text", IrStringType()), IrName("suffix", IrStringType())),
                IrBoolType(),
            ),
        )

    def test_lowers_string_ljust_method_call(self) -> None:
        module = lower_source_to_ir(
            "def pad(text: str, width: int, fill: str) -> str:\n"
            "    return text.ljust(width, fill)\n",
            filename="ljust.py",
        )
        returned = module.functions[0].body[0].value
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            returned,
            IrCall(
                "__str_ljust",
                (
                    IrName("text", IrStringType()),
                    IrName("width", int64),
                    IrName("fill", IrStringType()),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_string_rstrip_method_call(self) -> None:
        module = lower_source_to_ir(
            "def trim(text: str, chars: str) -> str:\n"
            "    return text.rstrip(chars)\n",
            filename="rstrip.py",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__str_rstrip",
                (IrName("text", IrStringType()), IrName("chars", IrStringType())),
                IrStringType(),
            ),
        )

    def test_lowers_string_predicate_method_calls(self) -> None:
        module = lower_source_to_ir(
            "def alpha(ch: str) -> bool:\n"
            "    return ch.isalpha()\n"
            "def digit(ch: str) -> bool:\n"
            "    return ch.isdigit()\n"
            "def alnum(ch: str) -> bool:\n"
            "    return ch.isalnum()\n"
            "def space(ch: str) -> bool:\n"
            "    return ch.isspace()\n",
            filename="string_predicates.py",
        )
        expected = (
            "__str_isalpha",
            "__str_isdigit",
            "__str_isalnum",
            "__str_isspace",
        )
        for function, target in zip(module.functions, expected, strict=True):
            self.assertEqual(
                function.body[0].value,
                IrCall(target, (IrName("ch", IrStringType()),), IrBoolType()),
            )

    def test_lowers_int_parse_call(self) -> None:
        module = lower_source_to_ir(
            "def parse(text: str) -> int:\n"
            "    return int(text, 16)\n",
            filename="int_parse.py",
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__int_parse",
                (IrName("text", IrStringType()), IrConstInt(16, int64)),
                int64,
            ),
        )

    def test_lowers_string_bool_or_as_value_expression_for_int_parse(self) -> None:
        module = lower_source_to_ir(
            "def parse(text: str) -> int:\n"
            "    return int(text or '0', 10)\n",
            filename="int_parse_default.py",
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__int_parse",
                (
                    IrCall(
                        "__ifexp",
                        (
                            IrName("text", IrStringType()),
                            IrName("text", IrStringType()),
                            IrConstString("0"),
                        ),
                        IrStringType(),
                    ),
                    IrConstInt(10, int64),
                ),
                int64,
            ),
        )

    def test_lowers_int_bool_call_as_ifexp(self) -> None:
        module = lower_source_to_ir(
            "def numeric(flag: bool) -> int:\n"
            "    return int(flag)\n",
            filename="int_bool.py",
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__ifexp",
                (
                    IrName("flag", IrBoolType()),
                    IrConstInt(1, int64),
                    IrConstInt(0, int64),
                ),
                int64,
            ),
        )

    def test_lowers_order_compare_arithmetic_operand_as_integer(self) -> None:
        module = lower_source_to_ir(
            "def before_end(s: str, i: int) -> bool:\n"
            "    return i + 1 < len(s)\n",
            filename="compare_arithmetic.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__cmp_Lt",
                (
                    IrBinary(
                        "+",
                        IrName("i", int64),
                        IrConstInt(1, int64),
                        int64,
                    ),
                    IrCall("len", (IrName("s", IrStringType()),), int64),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_bytes_size_expression_as_integer(self) -> None:
        module = lower_source_to_ir(
            "def padding(size: int, data: bytes) -> bytes:\n"
            "    return bytes(size - len(data))\n",
            filename="bytes_size_expr.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__bytes",
                (
                    IrBinary(
                        "-",
                        IrName("size", int64),
                        IrCall("len", (IrName("data", IrStringType()),), int64),
                        int64,
                    ),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_attribute_integer_add_assignment_when_function_returns_string(self) -> None:
        module = lower_source_to_ir(
            "class Scanner:\n"
            "    _index: int\n"
            "    def peek(self, offset: int = 0) -> str:\n"
            "        index = self._index + offset\n"
            "        return ''\n",
            filename="attribute_add_assignment.py",
            include_records={"Scanner"},
            include_functions={"Scanner.peek"},
        )
        int64 = IrIntType(64, signed=True)
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrBinary(
                "+",
                IrGetField(IrName("self", IrRecordType("Scanner")), "_index", int64),
                IrName("offset", int64),
                int64,
            ),
        )

    def test_lowers_bool_assignment_as_bool_when_function_returns_object(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "class ArrayDecl:\n"
            "    pass\n"
            "def classify(value: Any) -> Any:\n"
            "    unspecified = isinstance(value, int) or isinstance(value, ArrayDecl)\n"
            "    return value\n",
            filename="bool_assignment.py",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrCall(
                "__bool_or",
                (
                    IrCall(
                        "isinstance",
                        (IrName("value", IrRecordType("object")), IrName("int", IrBoolType())),
                        IrBoolType(),
                    ),
                    IrCall(
                        "isinstance",
                        (
                            IrName("value", IrRecordType("object")),
                            IrName("ArrayDecl", IrBoolType()),
                        ),
                        IrBoolType(),
                    ),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_value_or_assignment_with_operand_type_when_function_returns_object(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "class Type:\n"
            "    pass\n"
            "def choose(left: Type | None, right: Type | None) -> Any:\n"
            "    value = left or right\n"
            "    return value\n",
            filename="value_or_assignment.py",
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__ifexp")
        self.assertEqual(assigned.value.type, IrRecordType("Type | None"))

    def test_lowers_bool_or_with_negative_isinstance_int_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "def invalid(value: Any) -> bool:\n"
            "    return not isinstance(value, int) or value < 0\n",
            filename="bool_or_negative_isinstance.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        compare = returned.value.args[1]
        self.assertEqual(
            compare,
            IrCall(
                "__cmp_Lt",
                (IrName("value", int64), IrConstInt(0, int64)),
                IrBoolType(),
            ),
        )

    def test_lowers_value_and_with_not_none_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "from typing import Any\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "def choose(value: Type | None) -> Any:\n"
            "    return value is not None and value\n",
            filename="value_and_not_none.py",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__ifexp")
        self.assertEqual(returned.value.args[1], IrName("value", IrRecordType("Type")))

    def test_lowers_value_or_with_none_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "from typing import Any\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "def choose(value: Type | None) -> Any:\n"
            "    return value is None or value.name\n",
            filename="value_or_none.py",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__ifexp")
        self.assertEqual(
            returned.value.args[2],
            IrGetField(IrName("value", IrRecordType("Type")), "name", IrStringType()),
        )

    def test_lowers_value_and_without_guard_narrowing(self) -> None:
        module = lower_source_to_ir(
            "def choose(left: str, right: str) -> str:\n"
            "    return left and right\n",
            filename="value_and_plain.py",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__ifexp",
                (
                    IrName("left", IrStringType()),
                    IrName("right", IrStringType()),
                    IrName("left", IrStringType()),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_project_method_call_with_analyzed_signature_types(self) -> None:
        module = lower_source_to_ir(
            "class Scanner:\n"
            "    def _peek(self, offset: int = 0) -> str:\n"
            "        return ''\n"
            "    def _accept(self, *, flag: bool) -> bool:\n"
            "        return flag\n"
            "    def check(self) -> bool:\n"
            "        ch = self._peek()\n"
            "        return ch.isalpha() or self._peek(1).isdigit() or self._accept(flag=True)\n",
            filename="method_signature.py",
            include_records={"Scanner"},
            include_functions={"Scanner.check"},
        )
        int64 = IrIntType(64, signed=True)
        scanner = IrName("self", IrRecordType("Scanner"))
        self.assertEqual(
            module.functions[0].body[0],
            IrAssign("ch", IrCall("Scanner._peek", (scanner,), IrStringType())),
        )
        returned = module.functions[0].body[1].value
        self.assertEqual(
            returned,
            IrCall(
                "__bool_or",
                (
                    IrCall("__str_isalpha", (IrName("ch", IrStringType()),), IrBoolType()),
                    IrCall(
                        "__str_isdigit",
                        (
                            IrCall(
                                "Scanner._peek",
                                (scanner, IrConstInt(1, int64)),
                                IrStringType(),
                            ),
                        ),
                        IrBoolType(),
                    ),
                    IrCall(
                        "Scanner._accept",
                        (scanner, IrConstBool(True)),
                        IrBoolType(),
                    ),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_enum_member_attribute(self) -> None:
        module = lower_source_to_ir(
            "from enum import Enum, auto\n"
            "class Kind(Enum):\n"
            "    EOF = auto()\n"
            "def marker() -> Enum:\n"
            "    return Kind.EOF\n",
            filename="enum_member.py",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(returned, IrEnumMember("Kind", "EOF"))

    def test_lowers_class_int_constant_attribute(self) -> None:
        module = lower_source_to_ir(
            "class Kind:\n"
            "    POINTER = 12\n"
            "def pointer() -> int:\n"
            "    return Kind.POINTER\n",
            filename="class_int_constant.py",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(returned, IrConstInt(12, IrIntType(64, signed=True)))

    def test_lowers_init_assigned_instance_attribute_field_read(self) -> None:
        module = lower_source_to_ir(
            "class Box:\n"
            "    def __init__(self, value: int, flag: bool) -> None:\n"
            "        self.value = value\n"
            "        self.flag = flag\n"
            "        self.count = 0\n"
            "    def get(self) -> int:\n"
            "        return self.value\n",
            filename="init_fields.py",
            include_records={"Box"},
            include_functions={"Box.get"},
        )
        record = module.records[0]
        self.assertEqual([field.name for field in record.fields], ["value", "flag", "count"])
        self.assertEqual([field.type for field in record.fields], [IrIntType(64, True), IrBoolType(), IrIntType(64, True)])
        returned = module.functions[0].body[0].value
        self.assertEqual(returned, IrGetField(IrName("self", IrRecordType("Box")), "value", IrIntType(64, True)))

    def test_binds_init_assigned_instance_attribute_edge_types(self) -> None:
        analysis = analyze_source(
            "int32 = int\n"
            "Alias = list[int]\n"
            "class Box:\n"
            "    def make_text(self) -> str:\n"
            "        return 'x'\n"
            "    def __init__(self, value: int32, items: Alias, *, flag: bool) -> None:\n"
            "        self.value = value\n"
            "        self.items = items\n"
            "        self.flag = flag\n"
            "        self.none: None\n"
            "        self.empty = None\n"
            "        self.name = 'x'\n"
            "        self.cast = str(value)\n"
            "        self.same = self.name\n"
            "        self.text = Box.make_text()\n"
            "        self.truth = value == 0\n"
            "        self.negated = not flag\n"
            "        self.combo = self.name + self.text\n"
            "        self.floaty = 1.5\n"
            "        self.unknown = missing + value\n",
            filename="init_field_edges.py",
        )
        fields = analysis.types.classes["Box"].fields
        self.assertEqual(fields["value"], AotType("int32", bits=32, signed=True))
        self.assertEqual(fields["items"], AotType("list[int]"))
        self.assertEqual(fields["flag"], AotType("bool"))
        self.assertEqual(fields["none"], AotType("None"))
        self.assertEqual(fields["empty"], AotType("None"))
        self.assertEqual(fields["name"], AotType("str"))
        self.assertEqual(fields["cast"], AotType("str"))
        self.assertEqual(fields["same"], AotType("str"))
        self.assertEqual(fields["text"], AotType("str"))
        self.assertEqual(fields["truth"], AotType("bool"))
        self.assertEqual(fields["negated"], AotType("bool"))
        self.assertEqual(fields["combo"], AotType("str"))
        self.assertNotIn("floaty", fields)
        self.assertNotIn("unknown", fields)

    def test_init_field_inference_preserves_parameter_annotation_diagnostics(self) -> None:
        cases = (
            "class Bad:\n"
            "    def __init__(this) -> None:\n"
            "        pass\n",
            "class Bad:\n"
            "    def __init__(self, *, flag) -> None:\n"
            "        self.flag = flag\n",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(AotError):
                    analyze_source(source, filename="bad_init.py")

    def test_direct_binder_infers_none_expression_type(self) -> None:
        module = parse_source("", filename="direct.py")
        binder = _TypeBinder(check_subset(module), module)
        self.assertEqual(binder._infer_expr_type(None, {}, {}, {}), AotType("None"))

    def test_rejects_while_else_statement(self) -> None:
        with self.assertRaises(AotError) as ctx:
            lower_source_to_ir(
                "def spin() -> int:\n"
                "    while True:\n"
                "        return 1\n"
                "    else:\n"
                "        return 0\n",
                filename="while_else.py",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0004")

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

    def test_lowers_chained_comparison_as_boolean_and(self) -> None:
        module = lower_source_to_ir(
            "def in_range(value: int) -> bool:\n"
            "    return 1 <= value <= 3\n",
            filename="chained_compare.py",
        )
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__bool_and",
                (
                    IrCall(
                        "__cmp_LtE",
                        (IrConstInt(1, int64), IrName("value", int64)),
                        IrBoolType(),
                    ),
                    IrCall(
                        "__cmp_LtE",
                        (IrName("value", int64), IrConstInt(3, int64)),
                        IrBoolType(),
                    ),
                ),
                IrBoolType(),
            ),
        )

    def test_rejects_unsupported_expression(self) -> None:
        with self.assertRaises(AotError) as ctx:
            lower_source_to_ir(
                "int64 = int\ndef f() -> int64:\n    return {1: 2}\n",
                filename="bad.py",
                entry="f",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

    def test_rejects_unknown_name_call_target_and_field_access(self) -> None:
        cases = (
            ("def f() -> int:\n    return missing\n", "XCC-AOT-LOWER-0002"),
            ("def f() -> int:\n    return 1j\n", "XCC-AOT-LOWER-0002"),
            ("def f() -> int:\n    return helper()\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> int:\n    return int()\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> int:\n    return int('1', base=10)\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> bytes:\n    return bytes()\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> int:\n    return id()\n", "XCC-AOT-LOWER-0003"),
            (
                "def helper(value: int) -> int:\n"
                "    return value\n"
                "def f(values: tuple[str, ...]) -> int:\n"
                "    return helper(**values)\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f(values: tuple[str, ...]) -> str:\n    return str(**values)\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> bool:\n    return text.startswith()\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> bool:\n    return value.startswith('x')\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> bool:\n    return text.endswith()\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> bool:\n    return value.endswith('x')\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(values: tuple[str, ...]) -> tuple[str, ...]:\n"
                "    return reversed(values, key=True)\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f(value: int) -> int:\n    return reversed(value)\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> str:\n    return text.ljust()\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> str:\n    return value.ljust(4)\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> str:\n    return text.rstrip()\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> str:\n    return value.rstrip('x')\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> bytes:\n    return value.to_bytes(1)\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> bytes:\n    return text.to_bytes(1, 'little')\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> bool:\n    return text.isalpha('x')\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> bool:\n    return text.isspace(kind=True)\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> bool:\n    return value.isalpha()\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(text: str) -> bool:\n"
                "    return text.startswith('x', start=0)\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f(value: int) -> int:\n    return value.real\n", "XCC-AOT-LOWER-0002"),
            ("def build() -> int:\n    return 1\n"
             "def f() -> int:\n    return build().real\n", "XCC-AOT-LOWER-0002"),
            (
                "from dataclasses import dataclass\n"
                "@dataclass(frozen=True)\n"
                "class Pair:\n"
                "    value: int\n"
                "def f(pair: Pair) -> int:\n"
                "    return pair.missing\n",
                "XCC-AOT-LOWER-0002",
            ),
            ("def f(values: dict[str, int]) -> int:\n    return values.get()\n", "XCC-AOT-LOWER-0003"),
            ("def f(values: set[str]) -> str:\n    return values.get('x')\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(values: list[str]) -> int:\n"
                "    for pair in enumerate(values):\n"
                "        return 1\n"
                "    return 0\n",
                "XCC-AOT-LOWER-0001",
            ),
            (
                "def f(values: list[str]) -> int:\n"
                "    for index, name, extra in enumerate(values):\n"
                "        return index\n"
                "    return 0\n",
                "XCC-AOT-LOWER-0001",
            ),
            (
                "class Box:\n"
                "    def f(self, values: list[str]) -> int:\n"
                "        for index, self.name in enumerate(values):\n"
                "            return index\n"
                "        return 0\n",
                "XCC-AOT-LOWER-0001",
            ),
            (
                "def f(values: list[str]) -> int:\n"
                "    return enumerate(values, 1)\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "from xcc.llvm_api import llvm\n"
                "def f() -> int:\n"
                "    return llvm(1)\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "from xcc.llvm_api import llvm\n"
                "def f(module: int, name: str) -> int:\n"
                "    c = llvm()\n"
                "    return c.GetNamedFunction(module=module, name=name)\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "def f(name: str) -> str:\n"
                "    return name.encode(encoding='utf-8')\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f(value: int) -> str:\n    return value.encode()\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(left: str, right: str) -> str:\n"
                "    return left // right\n",
                "XCC-AOT-LOWER-0002",
            ),
            (
                "def f(value: int) -> str:\n"
                "    return chr(value, value)\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f() -> float:\n    return float()\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> float:\n    return float.fromhex()\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> int:\n    return len(range(start=1))\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(values: list[int]) -> list[int]:\n"
                "    return list(values)\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "def f(left: int, right: int) -> int:\n"
                "    return max(left, right, key=int)\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "from typing import Any\n"
                "def f(left: str, right: str) -> Any:\n"
                "    return max(left, right)\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f(value: str) -> list[str]:\n    return value.split()\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(value: str) -> int:\n"
                "    return value.find('x', 0, 1)\n",
                "XCC-AOT-LOWER-0003",
            ),
            ("def f(values: list[str]) -> list[str]:\n    return values.split(',')\n", "XCC-AOT-LOWER-0003"),
            ("def f(values: list[str]) -> int:\n    return values.find('x')\n", "XCC-AOT-LOWER-0003"),
            ("def f(values: list[str]) -> str:\n    return values.encode()\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> None:\n    for item in zip():\n        pass\n", "XCC-AOT-LOWER-0003"),
            (
                "def f(values: list[int]) -> None:\n"
                "    for item in zip(values, strict=False):\n"
                "        pass\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "def f(values: dict[str, int]) -> list[tuple[str, int]]:\n"
                "    return values.items(1)\n",
                "XCC-AOT-LOWER-0003",
            ),
            (
                "def f(values: list[int]) -> list[int]:\n"
                "    return values.items()\n",
                "XCC-AOT-LOWER-0003",
            ),
        )
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(AotError) as ctx:
                    lower_source_to_ir(source, filename="bad.py", entry="f")
                self.assertEqual(ctx.exception.diagnostics[0].code, code)

    def test_llvm_api_lowering_private_helpers_cover_edge_inputs(self) -> None:
        lowerer = _Lowerer("bad.py", {}, global_names={"llvm"})
        bad_call = ast.parse("llvm()", mode="eval").body
        self.assertIsInstance(bad_call, ast.Call)
        assert isinstance(bad_call, ast.Call)
        with self.assertRaises(AotError) as ctx:
            lowerer._lower_llvm_api_call(bad_call, {}, IrNoneType())
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0003")

        self.assertEqual(
            _llvm_api_call_return_type("SetTarget", IrIntType(64, signed=True)),
            IrNoneType(),
        )
        self.assertEqual(
            _llvm_api_call_return_type("CreateBuilder", IrRecordType("Builder")),
            IrRecordType("Builder"),
        )
        self.assertEqual(
            _llvm_api_call_return_type("CreateBuilder", IrNoneType()),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("GetBasicBlockTerminator", IrBoolType()),
            IrIntType(64, signed=True),
        )

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

        with self.assertRaises(AotError) as ctx:
            lowerer._lower_statement(ast.parse("del value\n").body[0], {}, IrNoneType())
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")

        with self.assertRaises(AotError) as ctx:
            lowerer._lower_expr(
                ast.parse("lambda: 1", mode="eval").body,
                {},
                IrRecordType("object"),
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

        missing_kwonly = ast.parse("def f(*, flag) -> int:\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(missing_kwonly, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")

        malformed_compare = ast.Compare(
            left=ast.Name("left", ast.Load()),
            ops=(),
            comparators=(),
        )
        with self.assertRaises(AotError) as ctx:
            lowerer._lower_compare(malformed_compare, {})
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0004")

        malformed_fstring = ast.JoinedStr([ast.Name("value", ast.Load())])
        with self.assertRaises(AotError) as ctx:
            lowerer._lower_joined_str(malformed_fstring, {})
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0005")

        unsupported_statement = ast.parse(
            "def f() -> int:\n"
            "    try:\n"
            "        return 1\n"
            "    except ValueError:\n"
            "        return 0\n"
        ).body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_statement, owner=None)
        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "Unsupported lowered statement: Try",
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
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("tuple[Node, ...]")),
            IrTupleType((IrRecordType("Node"),)),
        )
        self.assertEqual(lowerer._aot_type_to_ir_type(AotType("float")), IrFloatType())
        self.assertEqual(lowerer._aot_type_to_ir_type(AotType("Any")), IrRecordType("object"))
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("list[tuple[str, int]]")),
            IrTupleType((IrTupleType((IrStringType(), IrIntType(64, signed=True))),)),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("tuple[TypeOp, ...]")),
            IrTupleType((IrTupleType((IrStringType(), IrRecordType("object"))),)),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("tuple[DeclaratorOp, ...]")),
            IrTupleType((IrTupleType((IrStringType(), IrRecordType("object"))),)),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("FunctionParams")),
            IrTupleType((IrRecordType("object"), IrBoolType())),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("TypeOp")),
            IrTupleType((IrStringType(), IrRecordType("object"))),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("DeclaratorOp")),
            IrTupleType((IrStringType(), IrRecordType("object"))),
        )
        self.assertEqual(
            lowerer._type_name_to_ir_type("FunctionParams", ast.Pass()),
            IrTupleType((IrRecordType("object"), IrBoolType())),
        )
        self.assertEqual(
            lowerer._type_name_to_ir_type("TypeOp", ast.Pass()),
            IrTupleType((IrStringType(), IrRecordType("object"))),
        )
        self.assertEqual(
            lowerer._type_name_to_ir_type("DeclaratorOp", ast.Pass()),
            IrTupleType((IrStringType(), IrRecordType("object"))),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("dict[str, TypeOp]")),
            IrTupleType((IrStringType(), IrTupleType((IrStringType(), IrRecordType("object"))))),
        )
        self.assertIsNone(lowerer._optional_record_inner(IrIntType(64, signed=True)))
        self.assertEqual(lowerer._aot_type_to_ir_type(AotType("NoReturn")), IrNoneType())
        with self.assertRaises(AotError) as ctx:
            lowerer._record_field_type(IrIntType(64, signed=True), "value", ast.Pass())
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")
        with self.assertRaises(AotError) as ctx:
            lowerer._aot_type_to_ir_type(AotType("object"))
        self.assertEqual(ctx.exception.diagnostics[0].message, "Unsupported lowered type: object")

    def test_lowers_any_annotations_as_opaque_object(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "def echo(value: Any) -> Any:\n"
            "    return value\n",
            filename="any.py",
            entry="echo",
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrRecordType("object"))
        self.assertEqual(function.return_type, IrRecordType("object"))

    def test_lowers_bytes_annotations_as_string_type(self) -> None:
        module = lower_source_to_ir(
            "def echo(value: bytes) -> bytes:\n"
            "    return value\n",
            filename="bytes.py",
            entry="echo",
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrStringType())
        self.assertEqual(function.return_type, IrStringType())

    def test_lowers_bytes_builtin_constructor(self) -> None:
        module = lower_source_to_ir(
            "def zeroed(size: int) -> bytes:\n"
            "    return bytes(size)\n",
            filename="bytes_ctor.py",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__bytes",
                (IrName("size", IrIntType(64, signed=True)),),
                IrStringType(),
            ),
        )

    def test_lowers_id_builtin_call(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "def key(value: Any) -> int:\n"
            "    return id(value)\n",
            filename="id_builtin.py",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__id",
                (IrName("value", IrRecordType("object")),),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_int_to_bytes_method_call(self) -> None:
        module = lower_source_to_ir(
            "def encode(value: int, size: int) -> bytes:\n"
            "    return value.to_bytes(size, 'little')\n",
            filename="int_to_bytes.py",
        )
        returned = module.functions[0].body[0].value
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            returned,
            IrCall(
                "__int_to_bytes",
                (
                    IrName("value", int64),
                    IrName("size", int64),
                    IrConstString("little"),
                ),
                IrStringType(),
            ),
        )

    def test_direct_lowerer_narrowing_helpers_cover_edge_inputs(self) -> None:
        class_types = {
            "Base": AotClassInfo("Base", {}),
            "Child": AotClassInfo("Child", {}, ("Base",)),
        }
        lowerer = _Lowerer("narrow.py", class_types)
        self.assertFalse(_can_narrow_to_record(IrIntType(64, signed=True), "Child", class_types))
        self.assertTrue(_can_narrow_to_record(IrRecordType("object"), "Child", class_types))
        self.assertTrue(_record_extends("Child", "Child", class_types))
        self.assertFalse(_record_extends("Missing", "Base", class_types))

        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                ast.parse("isinstance(value.attr, Child)", mode="eval").body,
                {"value": IrRecordType("object")},
            )
        )
        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                ast.parse("isinstance(value, Missing)", mode="eval").body,
                {"value": IrRecordType("object")},
            )
        )
        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                ast.parse("isinstance(value, Child)", mode="eval").body,
                {"value": IrIntType(64, signed=True)},
            )
        )
        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                ast.parse("isinstance(value, (Child, 1))", mode="eval").body,
                {"value": IrRecordType("object")},
            )
        )
        self.assertEqual(
            lowerer._isinstance_guard_narrowing(
                ast.parse("isinstance(value, (Child, Base))", mode="eval").body,
                {"value": IrRecordType("object")},
            ),
            ("value", IrRecordType("Child | Base")),
        )
        self.assertEqual(
            _isinstance_target_names(ast.parse("(Child, Base)", mode="eval").body),
            ("Child", "Base"),
        )
        self.assertIsNone(_isinstance_target_names(ast.parse("(Child, 1)", mode="eval").body))
        self.assertIsNone(_isinstance_target_names(ast.parse("factory()", mode="eval").body))

        self.assertIsNone(lowerer._truthy_optional_record_narrowing(ast.Constant(True), {}))
        self.assertIsNone(
            lowerer._truthy_optional_record_narrowing(ast.Name("missing", ast.Load()), {})
        )
        self.assertIsNone(
            lowerer._truthy_optional_record_narrowing(
                ast.Name("value", ast.Load()),
                {"value": IrIntType(64, signed=True)},
            )
        )

        self.assertEqual(
            lowerer._not_none_guard_narrowing(
                ast.parse("None is not value", mode="eval").body,
                {"value": IrRecordType("Child | None")},
            ),
            ("value", IrRecordType("Child")),
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(ast.parse("None is not 1", mode="eval").body, {})
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(ast.parse("1 is not 2", mode="eval").body, {})
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(
                ast.parse("missing is not None", mode="eval").body,
                {},
            )
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(
                ast.parse("value is not None", mode="eval").body,
                {"value": IrIntType(64, signed=True)},
            )
        )
        self.assertIsNone(
            lowerer._none_bool_op_narrowing(
                ast.parse("value is None", mode="eval").body,
                {"value": IrIntType(64, signed=True)},
            )
        )

    def test_lowers_core_default_literal_and_runtime_shapes(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "from typing import Literal, NoReturn\n"
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
            "def abort() -> NoReturn:\n"
            "    raise ValueError('stop')\n"
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
        self.assertIsInstance(functions["abort"].return_type, IrNoneType)
        self.assertIsInstance(functions["abort"].body[0], IrRaise)
        self.assertEqual(functions["abort"].body[0].message.value, "stop")

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
        tree = ast.parse(
            "import os as operating_system\n"
            "import sys\n"
            "left, right = (1, 2)\n"
            "name: int = 1\n"
            "class Box:\n"
            "    pass\n"
            "42\n"
        )
        self.assertEqual(_collect_global_names(tree), {"operating_system", "sys", "name", "Box"})
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
        int64 = IrIntType(64, signed=True)
        fallback = IrRecordType("object")
        field_target = ast.parse("value.field = None\n").body[0].targets[0]
        self.assertEqual(
            lowerer._assignment_value_type(
                field_target,
                ast.Constant(None),
                {"value": int64},
                fallback,
            ),
            fallback,
        )
        self.assertEqual(
            lowerer._subscript_item_type(
                ast.Name("values", ast.Load()),
                {"values": IrTupleType((IrStringType(), IrIntType(64, signed=True)))},
                fallback,
            ),
            fallback,
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(ast.Constant(1.5), {}, fallback),
            fallback,
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                ast.parse("missing[0]", mode="eval").body,
                {},
                fallback,
            ),
            fallback,
        )
        mixed_ifexp = ast.parse("1 if flag else 'x'").body[0].value
        self.assertEqual(
            lowerer._infer_assignment_expr_type(mixed_ifexp, {"flag": IrBoolType()}, fallback),
            fallback,
        )
        mixed_bool = ast.parse("text or flag", mode="eval").body
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                mixed_bool,
                {"text": IrStringType(), "flag": IrBoolType()},
                fallback,
            ),
            fallback,
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                ast.parse("not flag", mode="eval").body,
                {"flag": IrBoolType()},
                fallback,
            ),
            IrBoolType(),
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                ast.parse("left + right", mode="eval").body,
                {"left": IrStringType(), "right": IrStringType()},
                fallback,
            ),
            IrStringType(),
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                ast.parse("left - right", mode="eval").body,
                {"left": IrStringType(), "right": IrStringType()},
                fallback,
            ),
            fallback,
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                ast.parse("value.missing", mode="eval").body,
                {"value": int64},
                fallback,
            ),
            fallback,
        )
        fixed_tuple_type = IrTupleType((IrStringType(), IrIntType(64, signed=True)))
        self.assertEqual(
            _tuple_subscript_result_type(ast.Name("index", ast.Load()), fixed_tuple_type),
            fallback,
        )
        self.assertEqual(
            _tuple_subscript_result_type(ast.parse("-1", mode="eval").body, fixed_tuple_type),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _tuple_subscript_result_type(ast.Constant(8), fixed_tuple_type),
            fallback,
        )
        self.assertEqual(_for_each_target_type(int64), fallback)
        self.assertIsNone(lowerer._tuple_backed_container_element_type("int", ast.Pass()))
        self.assertEqual(
            lowerer._tuple_backed_container_types("tuple[str, object]", ast.Pass()),
            (),
        )
        self.assertEqual(
            lowerer._tuple_backed_container_types("dict[str, object]", ast.Pass()),
            (),
        )
        self.assertEqual(
            lowerer._tuple_backed_container_types("list[object]", ast.Pass()),
            (),
        )
        self.assertIsNone(lowerer._optional_container_type("object", ast.Pass()))
        self.assertIsNone(_tuple_backed_container_element_name("list[...]"))
        self.assertIsNone(_tuple_backed_container_element_name("list["))
        self.assertIsNone(_dict_container_type_names("dict[str]"))

    def test_direct_lowerer_covers_record_union_field_edges(self) -> None:
        lowerer = _Lowerer(
            "union.py",
            {
                "Left": AotClassInfo("Left", {"value": AotType("str")}),
                "Right": AotClassInfo("Right", {"value": AotType("int")}),
                "Empty": AotClassInfo("Empty", {}),
            },
        )
        self.assertIsNone(
            lowerer._record_union_field_type("Left | None", "value", ast.Pass())
        )
        self.assertIsNone(
            lowerer._record_union_field_type("Left | Missing", "value", ast.Pass())
        )
        self.assertIsNone(
            lowerer._record_union_field_type("Left | Empty", "value", ast.Pass())
        )
        with self.assertRaises(AotError) as ctx:
            lowerer._record_union_field_type("Left | Right", "value", ast.Pass())
        self.assertEqual(ctx.exception.diagnostics[0].message, "Ambiguous union field access: value")

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
