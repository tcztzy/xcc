import unittest
from dataclasses import FrozenInstanceError

from tests import _bootstrap  # noqa: F401
from xcc.aot import py_ast as ast
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBreak,
    IrBytesType,
    IrCall,
    IrConstBool,
    IrConstBytes,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrDictType,
    IrEnumMember,
    IrExceptHandler,
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
    IrTry,
    IrWhile,
    analyze_source,
    lower_source_to_ir,
)
from xcc.aot.binder import _TypeBinder
from xcc.aot.cpython_ast_adapter import parse_cpython_expression, parse_cpython_source
from xcc.aot.ir import qualify_ir_entry, validate_ir_module
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


def _owned_parse(source: str, *, mode: str = "exec") -> ast.Module | ast.Expression:
    if mode == "eval":
        return parse_cpython_expression(source, filename="<test-expression>")
    if mode != "exec":
        raise ValueError(f"unsupported test parse mode: {mode}")
    return parse_source(source, filename="<test-module>").tree


def _hosted_owned_parse(source: str) -> ast.Module:
    return parse_cpython_source(source, filename="<test-module>")


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

    def test_qualifies_entry_before_emitting_process_main(self) -> None:
        int32 = IrIntType(32, signed=True)
        function = IrFunction("main", (), int32, (IrReturn(IrConstInt(0, int32)),))
        module = qualify_ir_entry(
            IrModule("program.py", (), (function,), entry="main"),
            "demo.program.main",
        )

        self.assertEqual(module.entry, "demo.program.main")
        self.assertEqual(module.functions[0].name, "demo.program.main")

    def test_ir_validator_rejects_duplicate_functions(self) -> None:
        int32 = IrIntType(32, signed=True)
        function = IrFunction("entry", (), int32, (IrReturn(IrConstInt(0, int32)),))
        with self.assertRaisesRegex(ValueError, "duplicate IR function: entry"):
            validate_ir_module(IrModule("duplicate.py", (), (function, function)))

    def test_ir_validator_rejects_missing_entry(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing IR entry: absent"):
            validate_ir_module(IrModule("missing.py", (), (), entry="absent"))


class AotScalarLoweringTests(unittest.TestCase):
    def test_lowers_single_argument_print_statement(self) -> None:
        module = lower_source_to_ir(
            "def main() -> int:\n"
            "    print('ready')\n"
            "    return 0\n",
            filename="print.py",
            entry="main",
        )

        self.assertEqual(module.functions[0].body[0], IrPrint(IrConstString("ready")))

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

    def test_lowers_static_two_digit_hex_fstring_format(self) -> None:
        module = lower_source_to_ir(
            "def render(value: int) -> str:\n"
            "    return f'{value:02X}:{value:02x}'\n",
            filename="fstring_hex.py",
            entry="render",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrStringConcat)
        assert isinstance(returned.value, IrStringConcat)
        formatted = tuple(
            part for part in returned.value.parts if isinstance(part, IrCall)
        )
        self.assertEqual(
            formatted,
            (
                IrCall(
                    "__int_format_hex2",
                    (IrName("value", IrIntType(64, signed=True)), IrConstBool(True)),
                    IrStringType(),
                ),
                IrCall(
                    "__int_format_hex2",
                    (IrName("value", IrIntType(64, signed=True)), IrConstBool(False)),
                    IrStringType(),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            lower_source_to_ir(
                "def render(value: int) -> str:\n"
                "    return f'{value:03d}'\n",
                filename="unsupported_fstring_format.py",
                entry="render",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0005")

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

    def test_lowers_omitted_call_arguments_from_signature_defaults(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = lower_source_to_ir(
            "def choose(offset: int = 1, enabled: bool = True, text: str = 'ok') -> int:\n"
            "    return offset\n"
            "def answer() -> int:\n"
            "    return choose()\n",
            filename="default_args.py",
            entry="answer",
        )

        returned = module.functions[1].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "choose",
                (IrConstInt(1, int64), IrConstBool(True), IrConstString("ok")),
                int64,
            ),
        )

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
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrAssign("value", IrConstInt(2, IrIntType(64, signed=True))),),
        )
        self.assertEqual(
            branch.finalbody.statements,
            (IrAssign("value", IrConstInt(3, IrIntType(64, signed=True))),),
        )

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
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )
        self.assertEqual(branch.handlers[0].exceptions, ("CodegenError",))

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
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )
        self.assertEqual(branch.handlers[0].exceptions, ("Exception",))

    def test_lowers_sema_error_try_except_normal_path(self) -> None:
        module = lower_source_to_ir(
            "class SemaError(Exception):\n"
            "    pass\n"
            "def f(value: int) -> int:\n"
            "    try:\n"
            "        return value\n"
            "    except SemaError:\n"
            "        return 0\n",
            filename="try_sema_error.py",
            entry="f",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )
        self.assertEqual(branch.handlers[0].exceptions, ("SemaError",))

    def test_lowers_parser_error_try_except_normal_path(self) -> None:
        module = lower_source_to_ir(
            "class ParserError(Exception):\n"
            "    pass\n"
            "def f(value: int) -> int:\n"
            "    try:\n"
            "        return value\n"
            "    except ParserError:\n"
            "        return 0\n",
            filename="try_parser_error.py",
            entry="f",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )
        self.assertEqual(branch.handlers[0].exceptions, ("ParserError",))

    def test_lowers_preprocessor_try_except_normal_path(self) -> None:
        module = lower_source_to_ir(
            "class PreprocessorError(Exception):\n"
            "    pass\n"
            "def f(value: int) -> int:\n"
            "    try:\n"
            "        return value\n"
            "    except OSError:\n"
            "        return 0\n"
            "    except PreprocessorError:\n"
            "        return 1\n",
            filename="try_preprocessor_error.py",
            entry="f",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )
        self.assertEqual(
            tuple(handler.exceptions for handler in branch.handlers),
            (("OSError",), ("PreprocessorError",)),
        )

    def test_lowers_tuple_exception_try_except_normal_path(self) -> None:
        module = lower_source_to_ir(
            "def f(value: int) -> int:\n"
            "    try:\n"
            "        return value\n"
            "    except (SyntaxError, ValueError):\n"
            "        return 0\n",
            filename="try_tuple_error.py",
            entry="f",
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrTry)
        assert isinstance(branch, IrTry)
        self.assertEqual(
            branch.body.statements,
            (IrReturn(IrName("value", IrIntType(64, signed=True))),),
        )
        self.assertEqual(branch.handlers[0].exceptions, ("SyntaxError", "ValueError"))

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

    def test_lowers_assert_bool_and_isinstance_builtin_int_narrowings(self) -> None:
        module = lower_source_to_ir(
            "def clamp(left: int | str, right: int | str) -> int:\n"
            "    assert isinstance(left, int) and isinstance(right, int)\n"
            "    return max(left, right)\n",
            filename="assert_bool_and_builtin_int.py",
            entry="clamp",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(
            returned.value.args[1],
            IrName("left", IrIntType(64, signed=True)),
        )
        self.assertEqual(
            returned.value.args[2],
            IrName("right", IrIntType(64, signed=True)),
        )

    def test_lowers_exiting_negative_isinstance_builtin_str_narrowing(self) -> None:
        module = lower_source_to_ir(
            "def length(value: str | int) -> int:\n"
            "    if not isinstance(value, str):\n"
            "        return 0\n"
            "    text = value\n"
            "    return len(text)\n",
            filename="if_not_isinstance_str_exit.py",
            entry="length",
        )
        assigned = module.functions[0].body[1]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value, IrName("value", IrStringType()))

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
        int64 = IrIntType(64, signed=True)
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

        whitespace = lower_source_to_ir(
            "def parts(value: str) -> tuple[str, ...]:\n"
            "    return value.split()\n",
            filename="split_whitespace.py",
            entry="parts",
        )
        self.assertEqual(
            whitespace.functions[0].body[0].value,
            IrCall(
                "__str_split_whitespace",
                (IrName("value", IrStringType()), IrConstInt(-1, int64)),
                IrTupleType((IrStringType(),)),
            ),
        )

        maxsplit = lower_source_to_ir(
            "def parts(value: str) -> tuple[str, ...]:\n"
            "    return value.split(None, 1)\n",
            filename="split_whitespace_maxsplit.py",
            entry="parts",
        )
        self.assertEqual(
            maxsplit.functions[0].body[0].value,
            IrCall(
                "__str_split_whitespace",
                (IrName("value", IrStringType()), IrConstInt(1, int64)),
                IrTupleType((IrStringType(),)),
            ),
        )

        explicit_maxsplit = lower_source_to_ir(
            "def parts(value: str) -> tuple[str, ...]:\n"
            "    return value.split('//', 1)\n",
            filename="split_explicit_maxsplit.py",
            entry="parts",
        )
        self.assertEqual(
            explicit_maxsplit.functions[0].body[0].value,
            IrCall(
                "__str_split_limit",
                (IrName("value", IrStringType()), IrConstString("//"), IrConstInt(1, int64)),
                IrTupleType((IrStringType(),)),
            ),
        )

    def test_lowers_string_splitlines_as_tuple_of_strings(self) -> None:
        default = lower_source_to_ir(
            "def lines(value: str) -> tuple[str, ...]:\n"
            "    return value.splitlines()\n",
            filename="splitlines_default.py",
            entry="lines",
        )
        self.assertEqual(
            default.functions[0].body[0].value,
            IrCall(
                "__str_splitlines",
                (IrName("value", IrStringType()), IrConstBool(False)),
                IrTupleType((IrStringType(),)),
            ),
        )

        keepends = lower_source_to_ir(
            "def lines(value: str) -> tuple[str, ...]:\n"
            "    return value.splitlines(keepends=True)\n",
            filename="splitlines_keepends.py",
            entry="lines",
        )
        self.assertEqual(
            keepends.functions[0].body[0].value,
            IrCall(
                "__str_splitlines",
                (IrName("value", IrStringType()), IrConstBool(True)),
                IrTupleType((IrStringType(),)),
            ),
        )

    def test_lowers_string_replace_method_call(self) -> None:
        module = lower_source_to_ir(
            "def splice(value: str) -> str:\n"
            "    return value.replace('\\\\\\n', '')\n",
            filename="replace.py",
            entry="splice",
        )
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__str_replace",
                (IrName("value", IrStringType()), IrConstString("\\\n"), IrConstString("")),
                IrStringType(),
            ),
        )

    def test_lowers_string_remove_affix_method_calls(self) -> None:
        module = lower_source_to_ir(
            "def drop_prefix(value: str) -> str:\n"
            "    return value.removeprefix('clang fp')\n"
            "def drop_suffix(value: str) -> str:\n"
            "    return value.removesuffix('.c')\n",
            filename="remove_affix.py",
        )
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__str_removeprefix",
                (IrName("value", IrStringType()), IrConstString("clang fp")),
                IrStringType(),
            ),
        )
        self.assertEqual(
            module.functions[1].body[0].value,
            IrCall(
                "__str_removesuffix",
                (IrName("value", IrStringType()), IrConstString(".c")),
                IrStringType(),
            ),
        )

    def test_lowers_string_lower_method_call(self) -> None:
        module = lower_source_to_ir(
            "def normalize(value: str) -> str:\n"
            "    return value.lower()\n",
            filename="lower.py",
            entry="normalize",
        )
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall("__str_lower", (IrName("value", IrStringType()),), IrStringType()),
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

    def test_lowers_global_string_constant_membership_as_literal(self) -> None:
        module = lower_source_to_ir(
            "HEX_DIGITS = '0123456789abcdefABCDEF'\n"
            "def is_hex(ch: str) -> bool:\n"
            "    return ch in HEX_DIGITS\n",
            filename="global_string_membership.py",
            entry="is_hex",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__cmp_In",
                (
                    IrName("ch", IrStringType()),
                    IrConstString("0123456789abcdefABCDEF"),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_global_scalar_literals_and_aliases_as_constants(self) -> None:
        module = lower_source_to_ir(
            "BASE = 8\n"
            "TAG = BASE\n"
            "NEGATIVE: int = -2\n"
            "ENABLED = True\n"
            "def values() -> tuple[int, int, bool]:\n"
            "    return TAG, NEGATIVE, ENABLED\n",
            filename="global_scalar_constants.py",
            entry="values",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrTuple(
                (
                    IrConstInt(8, IrIntType(64, signed=True)),
                    IrConstInt(-2, IrIntType(64, signed=True)),
                    IrConstBool(True),
                ),
                IrTupleType(
                    (
                        IrIntType(64, signed=True),
                        IrIntType(64, signed=True),
                        IrBoolType(),
                    )
                ),
            ),
        )

    def test_lowers_extra_global_scalar_constant_as_imported_literal(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = lower_source_to_ir(
            "def tag() -> int:\n"
            "    return IMPORTED_TAG\n",
            filename="imported_global_scalar.py",
            entry="tag",
            extra_global_scalar_constants={"IMPORTED_TAG": IrConstInt(8, int64)},
        )
        returned = module.functions[0].body[0]
        self.assertEqual(returned, IrReturn(IrConstInt(8, int64)))

    def test_lowers_global_string_set_membership_as_tuple_literal(self) -> None:
        module = lower_source_to_ir(
            "KEYWORDS = {'int', 'return'}\n"
            "def is_keyword(lexeme: str) -> bool:\n"
            "    return lexeme in KEYWORDS\n",
            filename="global_string_set_membership.py",
            entry="is_keyword",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__cmp_In",
                (
                    IrName("lexeme", IrStringType()),
                    IrTuple(
                        (IrConstString("int"), IrConstString("return")),
                        IrTupleType((IrStringType(),)),
                    ),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_sorted_global_string_container_alias_as_tuple_literal(self) -> None:
        module = lower_source_to_ir(
            "from typing import cast\n"
            "PUNCTUATORS: tuple[str, ...] = ('+', '>>=', '->')\n"
            "PUNCTUATORS_SORTED: tuple[str, ...] = cast(\n"
            "    tuple[str, ...], tuple(sorted(PUNCTUATORS, key=len, reverse=True))\n"
            ")\n"
            "def is_punctuator(lexeme: str) -> bool:\n"
            "    return lexeme in PUNCTUATORS_SORTED\n",
            filename="global_sorted_string_container.py",
            entry="is_punctuator",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__cmp_In",
                (
                    IrName("lexeme", IrStringType()),
                    IrTuple(
                        (IrConstString(">>="), IrConstString("->"), IrConstString("+")),
                        IrTupleType((IrStringType(),)),
                    ),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_ord_builtin_as_integer(self) -> None:
        module = lower_source_to_ir(
            "def codepoint(ch: str) -> int:\n"
            "    return ord(ch)\n",
            filename="ord_builtin.py",
            entry="codepoint",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__ord",
                (IrName("ch", IrStringType()),),
                IrIntType(64, signed=True),
            ),
        )
        byte_module = lower_source_to_ir(
            "def first(text: str) -> int:\n"
            "    for ch in text:\n"
            "        return ord(ch)\n"
            "    return 0\n",
            filename="ord_byte_iteration.py",
            entry="first",
        )
        loop = byte_module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        returned_character = loop.body.statements[0]
        self.assertIsInstance(returned_character, IrReturn)
        assert isinstance(returned_character, IrReturn)
        self.assertEqual(
            returned_character.value,
            IrCall(
                "__ord",
                (IrName("ch", IrStringType()),),
                IrIntType(64, signed=True),
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

    def test_lowers_module_alias_function_call_when_signature_known(self) -> None:
        lowerer = _Lowerer(
            "alias.py",
            {},
            {
                "_helper.is_ready": AotFunctionInfo(
                    "_helper.is_ready",
                    (("value", "int"),),
                    AotType("bool"),
                )
            },
            global_names={"_helper"},
        )
        expr = _owned_parse("_helper.is_ready(1)", mode="eval").body
        self.assertIsInstance(expr, ast.Call)
        assert isinstance(expr, ast.Call)

        lowered = lowerer._lower_call(expr, {}, IrBoolType())

        self.assertEqual(
            lowered,
            IrCall(
                "_helper.is_ready",
                (IrConstInt(1, IrIntType(64, signed=True)),),
                IrBoolType(),
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
        self.assertIsInstance(returned, IrCall)
        assert isinstance(returned, IrCall)
        self.assertEqual(returned.target, "__union_getattr")
        self.assertEqual(returned.args[0], IrName("expr", IrRecordType("Left | Right")))
        self.assertEqual(
            tuple(case.field for case in returned.args[2:] if isinstance(case, IrGetField)),
            ("value", "value"),
        )
        self.assertEqual(returned.type, IrIntType(64, signed=True))

    def test_guarded_union_attribute_preserves_narrowed_result_type(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class ItemA:\n"
            "    elements: int\n"
            "@dataclass(frozen=True)\n"
            "class ItemB:\n"
            "    other: int\n"
            "@dataclass(frozen=True)\n"
            "class Left:\n"
            "    item: ItemA\n"
            "@dataclass(frozen=True)\n"
            "class Right:\n"
            "    item: ItemB\n"
            "def read(value: Left | Right) -> int:\n"
            "    if not isinstance(value.item, ItemA):\n"
            "        raise ValueError('wrong item')\n"
            "    return value.item.elements\n",
            filename="guarded_union_attribute.py",
            entry="read",
        )
        function = next(function for function in module.functions if function.name == "read")
        returned = function.body[-1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrGetField)
        assert isinstance(returned.value, IrGetField)
        self.assertIsInstance(returned.value.value, IrCall)
        assert isinstance(returned.value.value, IrCall)
        self.assertEqual(returned.value.value.target, "__union_getattr")
        self.assertEqual(returned.value.value.type, IrRecordType("ItemA"))

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

    def test_lowers_exiting_none_guard_for_optional_bytes_receiver(self) -> None:
        module = lower_source_to_ir(
            "def padded(value: bytes | None, size: int) -> bytes | None:\n"
            "    if value is None:\n"
            "        return None\n"
            "    return value[:size].ljust(size, b'\\0')\n",
            filename="optional_bytes.py",
            entry="padded",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__bytes_ljust")
        self.assertEqual(returned.value.args[0].type, IrBytesType())

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

    def test_lowers_global_literal_pair_tuple_with_item_types(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = lower_source_to_ir(
            "_SIZES = ((\"char\", 1), (\"long\", 8))\n"
            "def size(name: str) -> int:\n"
            "    for candidate, value in _SIZES:\n"
            "        if name == candidate:\n"
            "            return value\n"
            "    return 0\n",
            filename="global_literal_pairs.py",
            entry="size",
        )
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertEqual(loop.iterable.type, IrTupleType((IrTupleType((IrStringType(), int64)),)))
        returned = loop.body.statements[0].then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("value", int64))

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

    def test_lowers_empty_tuple_literal_with_annotated_element_type(self) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "def make_params() -> int:\n"
            "    params: tuple[Type, ...] = ()\n"
            "    return 0\n",
            filename="empty_tuple_annotation.py",
            include_records={"Type"},
            entry="make_params",
        )

        assigned = module.functions[0].body[0]

        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value, IrTuple((), IrTupleType((IrRecordType("Type"),))))

    def test_lowers_empty_list_literal_with_annotated_element_type(self) -> None:
        module = lower_source_to_ir(
            "def make_values() -> int:\n"
            "    values: list[int] = []\n"
            "    values.append(0)\n"
            "    return 0\n",
            filename="empty_list_annotation.py",
            entry="make_values",
        )

        assigned = module.functions[0].body[0]
        append = module.functions[0].body[1]

        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value, IrTuple((), IrTupleType((IrIntType(64, True),))))
        self.assertIsInstance(append, IrAssign)
        assert isinstance(append, IrAssign)
        self.assertIsInstance(append.value, IrCall)
        assert isinstance(append.value, IrCall)
        self.assertEqual(append.value.args[1], IrConstInt(0, IrIntType(64, True)))

    def test_lowers_tuple_backed_attribute_append_as_field_assignment(self) -> None:
        module = lower_source_to_ir(
            "class Builder:\n"
            "    items: list[str]\n"
            "    def add(self, item: str) -> None:\n"
            "        self.items.append(item)\n",
            filename="attribute_append.py",
            include_records={"Builder"},
            include_functions={"Builder.add"},
        )

        append = module.functions[0].body[0]

        self.assertIsInstance(append, IrAssign)
        assert isinstance(append, IrAssign)
        self.assertEqual(append.target, "self.items")
        self.assertIsInstance(append.value, IrCall)
        assert isinstance(append.value, IrCall)
        self.assertEqual(append.value.target, "self.items.append")

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
        self.assertEqual(add.target, "__set_add")
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
        self.assertIsInstance(record.fields[0].type, IrDictType)
        self.assertTrue(
            all(isinstance(field.type, IrTupleType) for field in record.fields[1:])
        )
        self.assertEqual(record.fields[0].type, IrDictType(IrStringType(), IrIntType(64, True)))
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

    def test_lowers_for_target_from_homogeneous_fixed_tuple_literal(self) -> None:
        module = lower_source_to_ir(
            "def first_keyword_len() -> int:\n"
            "    for keyword in ('__asm__', '__asm', 'asm'):\n"
            "        return len(keyword)\n"
            "    return 0\n",
            filename="fixed_tuple_for.py",
            entry="first_keyword_len",
        )
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        returned = loop.body.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "len")
        self.assertEqual(returned.value.args[0].type, IrStringType())

    def test_lowers_for_each_over_string_as_one_character_string(self) -> None:
        module = lower_source_to_ir(
            "def fold(data: str) -> str:\n"
            "    result = ''\n"
            "    for ch in data:\n"
            "        result += ch.lower()\n"
            "    return result\n",
            filename="string_for_each.py",
            entry="fold",
        )

        loop = module.functions[0].body[1]

        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertEqual(loop.target, "ch")
        self.assertEqual(_for_each_target_type(loop.iterable.type), IrStringType())
        self.assertIn("IrName(name='ch', type=IrStringType())", repr(loop.body.statements[0]))

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

        started_item = lower_source_to_ir(
            "def first_index(names: list[str]) -> int:\n"
            "    for index, name in enumerate(names, start=1):\n"
            "        return index\n"
            "    return 0\n",
            filename="enumerate_start.py",
        )
        started_loop = started_item.functions[0].body[0]
        self.assertIsInstance(started_loop, IrForEach)
        assert isinstance(started_loop, IrForEach)
        self.assertIsInstance(started_loop.iterable, IrCall)
        assert isinstance(started_loop.iterable, IrCall)
        self.assertEqual(
            started_loop.iterable.args,
            (
                IrName("names", IrTupleType((IrStringType(),))),
                IrConstInt(1, IrIntType(64, True)),
            ),
        )

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

    def test_lowers_llvm_module_create_with_name_receiver_call(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def make_module(name: str) -> int:\n"
            "    c = llvm()\n"
            "    return c.ModuleCreateWithName(name.encode())\n",
            filename="llvm_module_create.py",
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_ModuleCreateWithName",
                (
                    IrCall(
                        "__str_encode",
                        (IrName("name", IrStringType()),),
                        IrBytesType(),
                    ),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_str_encode_as_bytes_for_llvm_api_call(self) -> None:
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
                    IrCall(
                        "__str_encode",
                        (IrName("name", IrStringType()),),
                        IrBytesType(),
                    ),
                ),
                IrIntType(64, signed=True),
            ),
        )

        encoded = lower_source_to_ir(
            "def encoded(name: str) -> bytes:\n"
            "    return name.encode('utf-8')\n",
            filename="str_encode_arg.py",
        )
        self.assertEqual(
            encoded.functions[0].body[0].value,
            IrCall(
                "__str_encode",
                (IrName("name", IrStringType()),),
                IrBytesType(),
            ),
        )

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
                (IrName("fn", IrIntType(64, signed=True)), IrConstBytes(b"entry")),
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

    def test_lowers_const_int_value_argument_as_integer_expression(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def value(offset: int | None) -> int:\n"
            "    c = llvm()\n"
            "    return c.ConstInt(c.Int64Type(), 0 if offset is None else offset, False)\n",
            filename="llvm_api_const_int_value.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_ConstInt",
                (
                    IrCall("__llvm_Int64Type", (), int64),
                    IrCall(
                        "__ifexp",
                        (
                            IrCall(
                                "__cmp_Is",
                                (IrName("offset", IrRecordType("int | None")), IrConstNone()),
                                IrBoolType(),
                            ),
                            IrConstInt(0, int64),
                            IrName("offset", int64),
                        ),
                        int64,
                    ),
                    IrConstBool(False),
                ),
                int64,
            ),
        )

    def test_lowers_nested_llvm_type_refs_as_integer_handles(self) -> None:
        module = lower_source_to_ir(
            "from xcc.llvm_api import llvm\n"
            "def null_padding(padding: int) -> int:\n"
            "    c = llvm()\n"
            "    return c.ConstNull(c.ArrayType(c.Int8Type(), padding))\n",
            filename="llvm_api_nested_type_ref.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__llvm_ConstNull",
                (
                    IrCall(
                        "__llvm_ArrayType",
                        (
                            IrCall("__llvm_Int8Type", (), int64),
                            IrName("padding", int64),
                        ),
                        int64,
                    ),
                ),
                int64,
            ),
        )

    def test_optional_integer_preserves_zero_distinct_from_none(self) -> None:
        module = lower_source_to_ir(
            "def read(value: int | None) -> int:\n"
            "    if value is None:\n"
            "        return 9\n"
            "    return value\n",
            filename="optional-int-zero.py",
            entry="read",
        )

        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrRecordType("int | None"))
        branch = function.body[0]
        self.assertIsInstance(branch, IrIf)
        returned = function.body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("value", IrIntType(64, signed=True)))

    def test_optional_integer_return_computes_unary_integer_before_boxing(self) -> None:
        module = lower_source_to_ir(
            "def maybe(value: int) -> int | None:\n"
            "    return -value\n",
            filename="optional-int-unary.py",
            entry="maybe",
        )

        function = module.functions[0]
        self.assertEqual(function.return_type, IrRecordType("int | None"))
        returned = function.body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value.type, IrIntType(64, signed=True))

    def test_optional_integer_or_fallback_narrows_truthy_arm(self) -> None:
        module = lower_source_to_ir(
            "def fallback(value: int | None) -> int:\n"
            "    return value or 0\n",
            filename="optional-int-or.py",
            entry="fallback",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.type, IrIntType(64, signed=True))
        self.assertEqual(
            returned.value.args[1],
            IrName("value", IrIntType(64, signed=True)),
        )

    def test_optional_integer_assignment_is_narrow_until_branch_merge(self) -> None:
        module = lower_source_to_ir(
            "def use(value: int) -> int:\n"
            "    return value\n"
            "def choose(flag: bool) -> tuple[int | None, int]:\n"
            "    selected: int | None = None\n"
            "    if flag:\n"
            "        selected = 3\n"
            "        close = use(selected)\n"
            "    else:\n"
            "        close = 0\n"
            "    return selected, close\n",
            filename="optional-int-flow.py",
            entry="choose",
        )

        function = next(function for function in module.functions if function.name == "choose")
        branch = function.body[1]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        call = branch.then_branch.statements[1]
        self.assertIsInstance(call, IrAssign)
        assert isinstance(call, IrAssign)
        self.assertEqual(
            call.value,
            IrCall(
                "use",
                (IrName("selected", IrIntType(64, signed=True)),),
                IrIntType(64, signed=True),
            ),
        )
        returned = function.body[2]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value.elements[0].type, IrRecordType("int | None"))

    def test_qualified_union_is_not_misclassified_as_suffix_record(self) -> None:
        lowerer = _Lowerer(
            "qualified-union.py",
            {
                "AST": AotClassInfo("AST", (), (), {}, {}),
                "PyToken": AotClassInfo("PyToken", (), (), {}, {}),
            },
            {},
        )

        self.assertIsNone(
            lowerer._project_record_name("PyToken | xcc.aot.py_ast.AST")
        )

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

    def test_lowers_string_subscript_as_string_result(self) -> None:
        module = lower_source_to_ir(
            "def pick(text: str, index: int) -> str:\n"
            "    return text[index]\n",
            filename="string_subscript.py",
            entry="pick",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__getitem",
                (IrName("text", IrStringType()), IrName("index", int64)),
                IrStringType(),
            ),
        )

    def test_infers_string_subscript_assignment_as_string_result(self) -> None:
        module = lower_source_to_ir(
            "def pick_ord(text: str, index: int) -> int:\n"
            "    ch = text[index]\n"
            "    return ord(ch)\n",
            filename="string_subscript_assignment.py",
            entry="pick_ord",
        )
        int64 = IrIntType(64, signed=True)
        function = module.functions[0]
        self.assertEqual(
            function.body[0],
            IrAssign(
                "ch",
                IrCall(
                    "__getitem",
                    (IrName("text", IrStringType()), IrName("index", int64)),
                    IrStringType(),
                ),
            ),
        )
        self.assertEqual(
            function.body[1],
            IrReturn(IrCall("__ord", (IrName("ch", IrStringType()),), int64)),
        )

    def test_lowers_string_repeat_count_as_integer_expression(self) -> None:
        module = lower_source_to_ir(
            "def pad(text: str, length: int) -> str:\n"
            "    return text + '\\0' * (length - len(text))\n",
            filename="string_repeat.py",
            entry="pad",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrStringConcat(
                (
                    IrName("text", IrStringType()),
                    IrCall(
                        "__str_repeat",
                        (
                            IrConstString("\0"),
                            IrBinary(
                                "-",
                                IrName("length", int64),
                                IrCall("len", (IrName("text", IrStringType()),), int64),
                                int64,
                            ),
                        ),
                        IrStringType(),
                    ),
                )
            ),
        )

    def test_lowers_tuple_repeat_and_concat_count_as_integer_expression(self) -> None:
        module = lower_source_to_ir(
            "def pad(values: list[int], length: int) -> list[int]:\n"
            "    return values + (0,) * (length - len(values))\n",
            filename="tuple_repeat.py",
            entry="pad",
        )
        int64 = IrIntType(64, signed=True)
        values_type = IrTupleType((int64,))
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__tuple_concat",
                (
                    IrName("values", values_type),
                    IrCall(
                        "__tuple_repeat",
                        (
                            IrTuple((IrConstInt(0, int64),), values_type),
                            IrBinary(
                                "-",
                                IrName("length", int64),
                                IrCall("len", (IrName("values", values_type),), int64),
                                int64,
                            ),
                        ),
                        values_type,
                    ),
                ),
                values_type,
            ),
        )

    def test_lowers_len_minus_constant_without_target_annotation(self) -> None:
        module = lower_source_to_ir(
            "def last(values: list[str]) -> int:\n"
            "    index = len(values) - 1\n"
            "    return index\n",
            filename="len_minus.py",
            entry="last",
        )
        int64 = IrIntType(64, signed=True)
        values_type = IrTupleType((IrStringType(),))
        self.assertEqual(
            module.functions[0].body[0],
            IrAssign(
                "index",
                IrBinary(
                    "-",
                    IrCall("len", (IrName("values", values_type),), int64),
                    IrConstInt(1, int64),
                    int64,
                ),
            ),
        )

    def test_infers_len_call_type_inside_integer_comparison(self) -> None:
        module = lower_source_to_ir(
            "def in_bounds(values: list[str], index: int) -> bool:\n"
            "    return index + len(values) < len(values)\n",
            filename="len_compare.py",
            entry="in_bounds",
        )
        int64 = IrIntType(64, signed=True)
        values_type = IrTupleType((IrStringType(),))
        self.assertEqual(
            module.functions[0].body[0].value,
            IrCall(
                "__cmp_Lt",
                (
                    IrBinary(
                        "+",
                        IrName("index", int64),
                        IrCall("len", (IrName("values", values_type),), int64),
                        int64,
                    ),
                    IrCall("len", (IrName("values", values_type),), int64),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_tuple_literal_plus_tuple_slice_as_tuple_concat(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    declarator_ops: tuple[tuple[str, int], ...]\n"
            "def resize(t: Type, inferred: int) -> Type:\n"
            "    new_ops = ((\"arr\", inferred),) + t.declarator_ops[1:]\n"
            "    return Type(new_ops)\n",
            filename="tuple_prefix_slice_concat.py",
            entry="resize",
        )
        int64 = IrIntType(64, signed=True)
        op_type = IrTupleType((IrStringType(), int64))
        ops_type = IrTupleType((op_type,))
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrCall(
                "__tuple_concat",
                (
                    IrTuple(
                        (
                            IrTuple(
                                (
                                    IrConstString("arr"),
                                    IrName("inferred", int64),
                                ),
                                op_type,
                            ),
                        ),
                        ops_type,
                    ),
                    IrTupleSlice(
                        IrGetField(
                            IrName("t", IrRecordType("Type")),
                            "declarator_ops",
                            ops_type,
                        ),
                        IrConstInt(1, int64),
                        None,
                    ),
                ),
                ops_type,
            ),
        )

    def test_lowers_dynamic_tuple_slice_bounds_as_ir_expressions(self) -> None:
        module = lower_source_to_ir(
            "def trim(values: list[int], start: int, stop: int) -> list[int]:\n"
            "    return values[start:stop]\n",
            filename="dynamic-tuple-slice.py",
            entry="trim",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrTupleSlice)
        assert isinstance(returned.value, IrTupleSlice)
        int64 = IrIntType(64, signed=True)
        self.assertEqual(returned.value.start, IrName("start", int64))
        self.assertEqual(returned.value.stop, IrName("stop", int64))

    def test_lowers_augmented_string_and_tuple_concat_without_numeric_binary(
        self,
    ) -> None:
        module = lower_source_to_ir(
            "def pad(text: str, values: list[int], length: int) -> str:\n"
            "    text += '\\0' * (length - len(text))\n"
            "    values += (0,) * (length - len(values))\n"
            "    return text\n",
            filename="augmented_repeat.py",
            entry="pad",
        )
        int64 = IrIntType(64, signed=True)
        values_type = IrTupleType((int64,))
        string_assign = module.functions[0].body[0]
        tuple_assign = module.functions[0].body[1]
        self.assertIsInstance(string_assign, IrAssign)
        self.assertIsInstance(tuple_assign, IrAssign)
        assert isinstance(string_assign, IrAssign)
        assert isinstance(tuple_assign, IrAssign)
        self.assertIsInstance(string_assign.value, IrStringConcat)
        self.assertEqual(
            tuple_assign.value,
            IrCall(
                "__tuple_concat",
                (
                    IrName("values", values_type),
                    IrCall(
                        "__tuple_repeat",
                        (
                            IrTuple((IrConstInt(0, int64),), values_type),
                            IrBinary(
                                "-",
                                IrName("length", int64),
                                IrCall("len", (IrName("values", values_type),), int64),
                                int64,
                            ),
                        ),
                        values_type,
                    ),
                ),
                values_type,
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

    def test_infers_ifexp_assignment_type_from_function_call_and_listcomp(self) -> None:
        module = lower_source_to_ir(
            "def decode(body: str) -> list[int]:\n"
            "    return []\n"
            "def choose(flag: bool, body: str, text: str) -> int:\n"
            "    units = decode(body) if flag else [ord(ch) for ch in text]\n"
            "    return len(units)\n",
            filename="ifexp_list_assignment.py",
            include_functions={"choose"},
        )
        int64 = IrIntType(64, signed=True)
        units_type = IrTupleType((int64,))
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value.type, units_type)
        self.assertEqual(
            assigned.value,
            IrCall(
                "__ifexp",
                (
                    IrName("flag", IrBoolType()),
                    IrCall("decode", (IrName("body", IrStringType()),), units_type),
                    IrCall("__ListComp", (), units_type),
                ),
                units_type,
            ),
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall("len", (IrName("units", units_type),), int64),
        )

    def test_ifexp_assignment_preserves_record_union_containing_other_arm(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Left:\n"
            "    value: int\n"
            "@dataclass(frozen=True)\n"
            "class Right:\n"
            "    value: int\n"
            "Value = Left | Right\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    items: tuple[Value, ...]\n"
            "def pick(box: Box, use_item: bool) -> int:\n"
            "    chosen = box.items[0] if use_item else Left(7)\n"
            "    if isinstance(chosen, Right):\n"
            "        return chosen.value + 4\n"
            "    return chosen.value\n",
            filename="ifexp_record_union_member.py",
            include_functions={"pick"},
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.value.type, IrRecordType("Left | Right"))

    def test_lowers_object_expected_ifexp_with_matching_integer_arms_as_integer(self) -> None:
        int64 = IrIntType(64, signed=True)
        lowerer = _Lowerer(
            "ifexp_int.py",
            {},
            {"fallback": AotFunctionInfo("fallback", (), AotType("int"))},
            global_names={"fallback"},
        )

        lowered = lowerer._lower_expr(
            _owned_parse("left if flag else fallback()", mode="eval").body,
            {"flag": IrBoolType(), "left": int64},
            IrRecordType("object"),
        )

        self.assertEqual(lowered.type, int64)
        self.assertIsInstance(lowered, IrCall)
        assert isinstance(lowered, IrCall)
        self.assertEqual(lowered.target, "__ifexp")
        self.assertEqual(lowered.args[1].type, int64)
        self.assertEqual(lowered.args[2].type, int64)

    def test_lowers_none_ifexp_with_int_call_arm_as_integer(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = lower_source_to_ir(
            "def maybe(right: int | None) -> int | None:\n"
            "    return None if right is None else int(bool(right))\n",
            filename="ifexp_optional_int_call.py",
            entry="maybe",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value.type, int64)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__ifexp")

    def test_infers_unary_minus_float_assignment_without_return_type_fallback(self) -> None:
        module = lower_source_to_ir(
            "def use(text: str) -> int:\n"
            "    value = float(text)\n"
            "    negative = -value\n"
            "    delta = 0.0 - value\n"
            "    return 0\n",
            filename="float_unary_assignment.py",
            entry="use",
        )

        assigned = module.functions[0].body[1]

        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(assigned.target, "negative")
        self.assertEqual(assigned.value.type, IrFloatType())
        delta = module.functions[0].body[2]
        self.assertIsInstance(delta, IrAssign)
        assert isinstance(delta, IrAssign)
        self.assertEqual(delta.target, "delta")
        self.assertEqual(delta.value.type, IrFloatType())

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
        expr = _owned_parse("path[0][1]", mode="eval").body

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

        unknown_index = _owned_parse("item[index]", mode="eval").body
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
                "values",
                IrCall(
                    "values.pop",
                    (IrName("values", IrTupleType((IrStringType(),))),),
                    IrTupleType((IrStringType(),)),
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
                        IrDictType(IrStringType(), IrIntType(64, signed=True)),
                    ),
                    IrName("key", IrStringType()),
                ),
                IrIntType(64, signed=True),
            ),
        )

    def test_lowers_global_annotated_dict_get_with_declared_container_type(self) -> None:
        module = lower_source_to_ir(
            "VALUES: dict[str, int] = {'x': 1}\n"
            "def lookup(name: str) -> int:\n"
            "    return VALUES.get(name)\n",
            filename="global_dict_get.py",
            include_functions={"lookup"},
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__dict_get",
                (
                    IrName("VALUES", IrDictType(IrStringType(), int64)),
                    IrName("name", IrStringType()),
                ),
                int64,
            ),
        )

    def test_lowers_ifexp_global_dict_get_with_declared_container_type(self) -> None:
        module = lower_source_to_ir(
            "LEFT: dict[str, int] = {'x': 1}\n"
            "RIGHT: dict[str, int] = {'y': 2}\n"
            "def lookup(flag: bool, name: str) -> int:\n"
            "    return (LEFT if flag else RIGHT).get(name)\n",
            filename="global_ifexp_dict_get.py",
            include_functions={"lookup"},
        )
        int64 = IrIntType(64, signed=True)
        dict_type = IrDictType(IrStringType(), int64)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__dict_get",
                (
                    IrCall(
                        "__ifexp",
                        (
                            IrName("flag", IrBoolType()),
                            IrName("LEFT", dict_type),
                            IrName("RIGHT", dict_type),
                        ),
                        dict_type,
                    ),
                    IrName("name", IrStringType()),
                ),
                int64,
            ),
        )

    def test_local_global_dict_annotation_wins_over_extra_string_container(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = lower_source_to_ir(
            "VALUES: dict[str, int] = {'x': 1}\n"
            "def lookup(name: str) -> int:\n"
            "    return VALUES.get(name)\n",
            filename="global_dict_collision.py",
            include_functions={"lookup"},
            extra_global_string_container_constants={
                "VALUES": IrTuple((IrConstString("x"),), IrTupleType((IrStringType(),))),
            },
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__dict_get",
                (
                    IrName("VALUES", IrDictType(IrStringType(), int64)),
                    IrName("name", IrStringType()),
                ),
                int64,
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

    def test_lowers_isinstance_guard_from_object_optional_to_record(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class InitList:\n"
            "    items: tuple[int, ...]\n"
            "def size(value: object | None) -> int:\n"
            "    if isinstance(value, InitList):\n"
            "        return len(value.items)\n"
            "    return 0\n",
            filename="object_optional_isinstance.py",
            entry="size",
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
                        IrName("value", IrRecordType("InitList")),
                        "items",
                        IrTupleType((IrIntType(64, signed=True),)),
                    ),
                ),
                IrIntType(64, signed=True),
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

    def test_lowers_isinstance_tuple_guarded_function_params_union(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "FunctionParams = tuple[tuple[Type, ...] | None, bool]\n"
            "def param_len(value: int | FunctionParams) -> int:\n"
            "    assert isinstance(value, tuple) and len(value) == 2\n"
            "    return len(value)\n",
            filename="isinstance_tuple_function_params.py",
        )
        int64 = IrIntType(64, signed=True)
        function_params = IrTupleType((IrTupleType((IrRecordType("Type"),)), IrBoolType()))
        assertion = module.functions[0].body[0]
        self.assertIsInstance(assertion, IrAssign)
        assert isinstance(assertion, IrAssign)
        condition = assertion.value.args[0]
        self.assertIsInstance(condition, IrCall)
        assert isinstance(condition, IrCall)
        len_compare = condition.args[1]
        self.assertIsInstance(len_compare, IrCall)
        assert isinstance(len_compare, IrCall)
        guarded_len = len_compare.args[0]
        self.assertEqual(guarded_len, IrCall("len", (IrName("value", function_params),), int64))
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrCall("len", (IrName("value", function_params),), int64))

    def test_lowers_integer_binop_in_union_tuple_slot_from_inferred_operands(self) -> None:
        module = lower_source_to_ir(
            "FunctionParams = tuple[tuple[str, ...] | None, bool]\n"
            "TypeOp = tuple[str, int | FunctionParams]\n"
            "def make_array_op(name: str) -> TypeOp:\n"
            "    return ('arr', len(name) + 1)\n",
            filename="union_tuple_integer_binop.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrTuple)
        assert isinstance(returned.value, IrTuple)
        self.assertEqual(returned.value.elements[0], IrConstString("arr"))
        self.assertEqual(
            returned.value.elements[1],
            IrBinary(
                "+",
                IrCall("len", (IrName("name", IrStringType()),), int64),
                IrConstInt(1, int64),
                int64,
            ),
        )

    def test_continue_branch_narrowing_does_not_leak_to_following_if(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class TypeSpec:\n"
            "    name: str\n"
            "FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]\n"
            "DeclaratorValue = int | FunctionDeclarator\n"
            "DeclaratorOp = tuple[str, DeclaratorValue]\n"
            "def f(ops: tuple[DeclaratorOp, ...]) -> int:\n"
            "    for kind, value in ops:\n"
            "        if kind == 'arr':\n"
            "            assert isinstance(value, int)\n"
            "            continue\n"
            "        if kind == 'fn':\n"
            "            assert isinstance(value, tuple) and len(value) == 2\n"
            "            return len(value)\n"
            "    return 0\n",
            filename="continue_narrow.py",
        )
        int64 = IrIntType(64, signed=True)
        function_declarator = IrTupleType((IrTupleType((IrRecordType("TypeSpec"),)), IrBoolType()))
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        fn_branch = loop.body.statements[1]
        self.assertIsInstance(fn_branch, IrIf)
        assert isinstance(fn_branch, IrIf)
        assertion = fn_branch.then_branch.statements[0]
        self.assertIsInstance(assertion, IrAssign)
        assert isinstance(assertion, IrAssign)
        condition = assertion.value.args[0]
        self.assertIsInstance(condition, IrCall)
        assert isinstance(condition, IrCall)
        len_compare = condition.args[1]
        self.assertIsInstance(len_compare, IrCall)
        assert isinstance(len_compare, IrCall)
        guarded_len = len_compare.args[0]
        self.assertEqual(
            guarded_len,
            IrCall("len", (IrName("value", function_declarator),), int64),
        )

    def test_lowers_starred_tuple_backed_container_literal_as_concat(self) -> None:
        module = lower_source_to_ir(
            "def merge(left: list[str], right: list[str]) -> list[str]:\n"
            "    return [*left, *right]\n",
            filename="starred_list.py",
        )
        values_type = IrTupleType((IrStringType(),))
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__tuple_concat",
                (IrName("left", values_type), IrName("right", values_type)),
                values_type,
            ),
        )

    def test_lowers_one_argument_dict_constructor_as_tuple_backed_copy(self) -> None:
        module = lower_source_to_ir(
            "def clone(values: dict[str, int]) -> dict[str, int]:\n"
            "    return dict(values)\n",
            filename="dict_constructor.py",
        )
        dict_type = IrDictType(IrStringType(), IrIntType(64, signed=True))
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrName("values", dict_type))

    def test_lowers_set_constructor_from_dict_as_deduplicated_keys(self) -> None:
        module = lower_source_to_ir(
            "def names(values: dict[str, int]) -> frozenset[str]:\n"
            "    return frozenset(values)\n",
            filename="set_from_dict.py",
            entry="names",
        )
        dict_type = IrDictType(IrStringType(), IrIntType(64, signed=True))
        keys_type = IrTupleType((IrStringType(),))
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__set_union",
                (
                    IrTuple((), keys_type),
                    IrCall(
                        "__dict_keys",
                        (IrName("values", dict_type),),
                        keys_type,
                    ),
                ),
                keys_type,
            ),
        )

    def test_lowers_set_update_from_dict_as_alias_visible_key_union(self) -> None:
        module = lower_source_to_ir(
            "def merge(values: set[str], incoming: dict[str, int]) -> int:\n"
            "    values.update(incoming)\n"
            "    return len(values)\n",
            filename="set_update_dict.py",
            entry="merge",
        )
        keys_type = IrTupleType((IrStringType(),))
        dict_type = IrDictType(IrStringType(), IrIntType(64, signed=True))
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrCall(
                "__set_update",
                (
                    IrName("values", keys_type),
                    IrCall(
                        "__dict_keys",
                        (IrName("incoming", dict_type),),
                        keys_type,
                    ),
                ),
                keys_type,
            ),
        )

    def test_lowers_direct_set_equality_without_tuple_order_semantics(self) -> None:
        module = lower_source_to_ir(
            "def matches(text: str) -> bool:\n"
            "    return {part.strip() for part in text.split('|')} == {'None', 'int'}\n",
            filename="set_equality.py",
            entry="matches",
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__set_equal")
        self.assertEqual(len(returned.value.args), 2)
        self.assertIsInstance(returned.value.args[0], IrCall)
        assert isinstance(returned.value.args[0], IrCall)
        self.assertEqual(returned.value.args[0].target, "__set_comprehension")
        self.assertIsInstance(returned.value.args[1], IrTuple)

    def test_lowers_dict_subscript_result_as_value_type_not_optional_get(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Signature:\n"
            "    return_type: str\n"
            "def result(sigs: dict[str, Signature], name: str) -> str:\n"
            "    return sigs[name].return_type\n",
            filename="dict_subscript_value.py",
        )
        signature_type = IrRecordType("Signature")
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrCall(
                    "__dict_get",
                    (
                        IrName("sigs", IrDictType(IrStringType(), signature_type)),
                        IrName("name", IrStringType()),
                    ),
                    signature_type,
                ),
                "return_type",
                IrStringType(),
            ),
        )

    def test_lowers_dict_setdefault_as_alias_visible_insert_or_lookup(self) -> None:
        module = lower_source_to_ir(
            "def ensure(values: dict[str, list[int]], name: str) -> list[int]:\n"
            "    return values.setdefault(name, [])\n",
            filename="dict_setdefault.py",
        )
        value_type = IrTupleType((IrIntType(64, signed=True),))
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__dict_setdefault",
                (
                    IrName("values", IrDictType(IrStringType(), value_type)),
                    IrName("name", IrStringType()),
                    IrTuple((), value_type),
                ),
                value_type,
            ),
        )

    def test_lowers_property_attribute_access_as_getter_call(self) -> None:
        module = lower_source_to_ir(
            "class Box:\n"
            "    def __init__(self, value: str) -> None:\n"
            "        self._value = value\n"
            "    @property\n"
            "    def value(self) -> str:\n"
            "        return self._value\n"
            "def read(box: Box) -> str:\n"
            "    return box.value\n",
            filename="property_getter.py",
        )
        returned = module.functions[-1].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall("Box.value", (IrName("box", IrRecordType("Box")),), IrStringType()),
        )

    def test_lowers_nested_for_tuple_target_with_temp_unpack(self) -> None:
        module = lower_source_to_ir(
            "def compare(left: list[tuple[str, int]], right: list[tuple[str, int]]) -> int:\n"
            "    for (kind_a, val_a), (kind_b, val_b) in zip(left, right, strict=True):\n"
            "        return val_a + val_b\n"
            "    return 0\n",
            filename="nested_for_target.py",
        )
        int64 = IrIntType(64, signed=True)
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertTrue(loop.target.startswith("__for_item_"))
        assigned_names = tuple(
            statement.target for statement in loop.body.statements[:4] if isinstance(statement, IrAssign)
        )
        self.assertEqual(assigned_names, ("kind_a", "val_a", "kind_b", "val_b"))
        returned = loop.body.statements[4]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrBinary("+", IrName("val_a", int64), IrName("val_b", int64), int64),
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
                        IrDictType(IrStringType(), IrIntType(64, signed=True)),
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

    def test_prefers_unique_qualified_project_method_target(self) -> None:
        lookup_info = AotFunctionInfo(
            "Scope.lookup",
            (("self", "Scope"), ("name", "str")),
            AotType("int"),
        )
        module = lower_source_to_ir(
            "class Scope:\n"
            "    pass\n"
            "class Owner:\n"
            "    def __init__(self, scope: Scope) -> None:\n"
            "        self.scope = scope\n"
            "    def read(self) -> int:\n"
            "        return self.scope.lookup('x')\n",
            filename="qualified_method.py",
            include_records={"Owner", "Scope"},
            include_functions={"Owner.read"},
            extra_functions={
                "Scope.lookup": lookup_info,
                "xcc.sema.symbols.Scope.lookup": lookup_info,
            },
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "xcc.sema.symbols.Scope.lookup")

    def test_cast_any_refines_project_role_by_argument_name(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any, cast\n"
            "class Type:\n"
            "    def is_array(self) -> bool:\n"
            "        return True\n"
            "class Analyzer:\n"
            "    def _resolve_type(self, spec: object) -> Type:\n"
            "        return Type()\n"
            "def f(analyzer: object, spec: object) -> bool:\n"
            "    a = cast(Any, analyzer)\n"
            "    var_type = a._resolve_type(spec)\n"
            "    return var_type.is_array()\n",
            filename="object_receiver_unique_method.py",
            include_records={"Analyzer", "Type"},
            include_functions={"f"},
        )
        assignment = module.functions[0].body[1]
        self.assertIsInstance(assignment, IrAssign)
        assert isinstance(assignment, IrAssign)
        self.assertIsInstance(assignment.value, IrCall)
        assert isinstance(assignment.value, IrCall)
        self.assertEqual(assignment.value.target, "Analyzer._resolve_type")
        self.assertEqual(assignment.value.type, IrRecordType("Type"))
        returned = module.functions[0].body[2]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "Type.is_array")

    def test_object_name_refines_project_role_by_argument_name(self) -> None:
        module = lower_source_to_ir(
            "class TypeMap:\n"
            "    pass\n"
            "class Analyzer:\n"
            "    _type_map: TypeMap\n"
            "def f(analyzer: object) -> TypeMap:\n"
            "    return analyzer._type_map\n",
            filename="object_role_name.py",
            include_records={"Analyzer", "TypeMap"},
            include_functions={"f"},
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrName("analyzer", IrRecordType("Analyzer")),
                "_type_map",
                IrRecordType("TypeMap"),
            ),
        )

    def test_lowers_type_name_attribute_to_static_record_name(self) -> None:
        module = lower_source_to_ir(
            "class Stmt:\n"
            "    pass\n"
            "def f(stmt: Stmt) -> str:\n"
            "    return type(stmt).__name__\n",
            filename="type_name_attribute.py",
            include_records={"Stmt"},
            include_functions={"f"},
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(returned.value, IrConstString("Stmt"))

    def test_not_none_narrows_multi_record_optional_union(self) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "class VarSymbol:\n"
            "    type_: Type\n"
            "class EnumConstSymbol:\n"
            "    type_: Type\n"
            "def f(symbol: VarSymbol | EnumConstSymbol | None) -> Type:\n"
            "    if symbol is not None:\n"
            "        return symbol.type_\n"
            "    return Type()\n",
            filename="not_none_multi_union.py",
            include_records={"EnumConstSymbol", "Type", "VarSymbol"},
            include_functions={"f"},
        )
        branch = module.functions[0].body[0]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrName("symbol", IrRecordType("VarSymbol | EnumConstSymbol")),
                "type_",
                IrRecordType("Type"),
            ),
        )

    def test_annotated_optional_none_initializer_preserves_annotation(self) -> None:
        module = lower_source_to_ir(
            "class Signature:\n"
            "    params: int\n"
            "def f(flag: bool, signature: Signature) -> int:\n"
            "    best_signature: Signature | None = None\n"
            "    if flag:\n"
            "        best_signature = signature\n"
            "    if best_signature is None:\n"
            "        return 0\n"
            "    return best_signature.params\n",
            filename="optional_none_annotation.py",
            include_records={"Signature"},
            include_functions={"f"},
        )
        returned = module.functions[0].body[-1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrName("best_signature", IrRecordType("Signature")),
                "params",
                IrIntType(64, signed=True),
            ),
        )

    def test_exiting_or_none_guard_narrows_all_optional_records(self) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    name: str\n"
            "def f(left: Type | None, right: Type | None) -> bool:\n"
            "    if left is None or right is None:\n"
            "        return False\n"
            "    return left.name == right.name\n",
            filename="or_none_guard_all.py",
            include_records={"Type"},
            include_functions={"f"},
        )
        returned = module.functions[0].body[-1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIn("IrName(name='left', type=IrRecordType(name='Type'))", repr(returned))
        self.assertIn("IrName(name='right', type=IrRecordType(name='Type'))", repr(returned))

    def test_exiting_or_negative_isinstance_guard_narrows_all_records(self) -> None:
        module = lower_source_to_ir(
            "class Expr:\n"
            "    pass\n"
            "class CallExpr(Expr):\n"
            "    callee: Expr\n"
            "class Identifier(Expr):\n"
            "    name: str\n"
            "def f(expr: Expr) -> str:\n"
            "    if not isinstance(expr, CallExpr) or not isinstance(expr.callee, Identifier):\n"
            "        return ''\n"
            "    return expr.callee.name\n",
            filename="or_negative_isinstance_guard_all.py",
            include_records={"CallExpr", "Expr", "Identifier"},
            include_functions={"f"},
        )
        returned = module.functions[0].body[-1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIn("IrName(name='expr', type=IrRecordType(name='CallExpr'))", repr(returned))
        self.assertIn(
            "field='callee', type=IrRecordType(name='Identifier')",
            repr(returned),
        )

    def test_extra_aliases_resolve_cross_module_tuple_field_types(self) -> None:
        module = lower_source_to_ir(
            "class TypeSpec:\n"
            "    source_line: int | None\n"
            "class Expr:\n"
            "    pass\n"
            "class GenericExpr:\n"
            "    associations: tuple[GenericAssociation, ...]\n"
            "def f(expr: GenericExpr) -> int:\n"
            "    for association_index, (assoc_type_spec, assoc_expr) in enumerate(\n"
            "        expr.associations, start=1\n"
            "    ):\n"
            "        if assoc_type_spec is not None:\n"
            "            return assoc_type_spec.source_line\n"
            "    return 0\n",
            filename="cross_module_alias.py",
            include_records={"Expr", "GenericExpr", "TypeSpec"},
            include_functions={"f"},
            extra_aliases={
                "GenericAssociation": AotType("tuple['TypeSpec | None', 'Expr']")
            },
        )
        loop = module.functions[0].body[0]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        branch = loop.body.statements[-1]
        self.assertIsInstance(branch, IrIf)
        assert isinstance(branch, IrIf)
        returned = branch.then_branch.statements[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrGetField(
                IrName("assoc_type_spec", IrRecordType("TypeSpec")),
                "source_line",
                IrIntType(64, signed=True),
            ),
        )

    def test_bool_and_skips_definitely_false_isinstance_tail(self) -> None:
        module = lower_source_to_ir(
            "FunctionParams = tuple[object, bool]\n"
            "class ArrayDecl:\n"
            "    length: int | None\n"
            "def f(value: int | FunctionParams) -> bool:\n"
            "    return isinstance(value, ArrayDecl) and value.length is None\n",
            filename="false_isinstance_tail.py",
            include_records={"ArrayDecl"},
            include_functions={"f"},
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall("__bool_and", (IrConstBool(False),), IrBoolType()),
        )

    def test_lowers_fstring_integer_expression_with_numeric_type(self) -> None:
        module = lower_source_to_ir(
            "def f(index: int) -> str:\n"
            "    return f'Argument {index + 1} type mismatch'\n",
            filename="fstring_int_expr.py",
            include_functions={"f"},
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrStringConcat)
        assert isinstance(returned.value, IrStringConcat)
        self.assertIsInstance(returned.value.parts[1], IrBinary)

    def test_lowers_zip_with_explicit_strict_false(self) -> None:
        module = lower_source_to_ir(
            "def f(left: tuple[int, ...], right: tuple[int, ...]) -> int:\n"
            "    total = 0\n"
            "    for a, b in zip(left, right, strict=False):\n"
            "        total += a + b\n"
            "    return total\n",
            filename="zip_strict_false.py",
            include_functions={"f"},
        )
        loop = module.functions[0].body[1]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        self.assertIsInstance(loop.iterable, IrCall)
        assert isinstance(loop.iterable, IrCall)
        self.assertEqual(loop.iterable.target, "__zip")

    def test_cross_module_signature_uses_fallback_for_unsupported_parameter_type(self) -> None:
        module = lower_source_to_ir(
            "from xcc.parser import parse\n"
            "class Options:\n"
            "    std: str\n"
            "class TranslationUnit:\n"
            "    pass\n"
            "def f(options: Options) -> TranslationUnit:\n"
            "    return parse((), std=options.std)\n",
            filename="unsupported_signature_arg.py",
            include_records={"Options", "TranslationUnit"},
            include_functions={"f"},
            extra_functions={
                "parse": AotFunctionInfo(
                    "parse",
                    (("tokens", "tuple[object, ...]"), ("std", "StdMode")),
                    AotType("TranslationUnit"),
                )
            },
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "parse",
                (
                    IrTuple((), IrTupleType((IrRecordType("object"),))),
                    IrGetField(IrName("options", IrRecordType("Options")), "std", IrStringType()),
                ),
                IrRecordType("TranslationUnit"),
            ),
        )

    def test_lowers_optional_record_receiver_method_with_known_signature(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any\n"
            "class Type:\n"
            "    pass\n"
            "def f(callee_type: Type | None) -> Any:\n"
            "    callable_signature = None if callee_type is None else callee_type.callable_signature()\n"
            "    return callable_signature\n",
            filename="optional_receiver_method.py",
            include_records={"Type"},
            include_functions={"f"},
            extra_functions={
                "Type.callable_signature": AotFunctionInfo(
                    "Type.callable_signature",
                    (("self", "Type"),),
                    AotType("tuple[Type, FunctionParams] | None"),
                )
            },
        )
        callable_signature_type = IrTupleType(
            (IrRecordType("Type"), IrTupleType((IrRecordType("object"), IrBoolType())))
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value,
            IrCall(
                "__ifexp",
                (
                    IrCall(
                        "__cmp_Is",
                        (IrName("callee_type", IrRecordType("Type | None")), IrConstNone()),
                        IrBoolType(),
                    ),
                    IrConstNone(),
                    IrCall(
                        "Type.callable_signature",
                        (IrName("callee_type", IrRecordType("Type")),),
                        callable_signature_type,
                    ),
                ),
                callable_signature_type,
            ),
        )
        returned = module.functions[0].body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrName("callable_signature", callable_signature_type),
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
            IrTuple((), IrDictType(IrStringType(), IrIntType(64, signed=True))),
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

    def test_lowers_nested_dict_subscript_assignment_as_stack_replacement(self) -> None:
        int64 = IrIntType(64, signed=True)
        dict_type = IrDictType(IrStringType(), int64)
        stack_type = IrTupleType((dict_type,))
        module = lower_source_to_ir(
            "def store(stack: list[dict[str, int]], name: str, item: int) -> None:\n"
            "    stack[-1][name] = item\n",
            filename="nested_dict_assign.py",
        )

        statement = module.functions[0].body[0]
        self.assertIsInstance(statement, IrSetItem)
        assert isinstance(statement, IrSetItem)
        self.assertEqual(statement.target, IrName("stack", stack_type))
        self.assertEqual(statement.index, IrConstInt(-1, int64))
        self.assertEqual(
            statement.value,
            IrCall(
                "__dict_set",
                (
                    IrCall(
                        "__getitem",
                        (IrName("stack", stack_type), IrConstInt(-1, int64)),
                        dict_type,
                    ),
                    IrName("name", IrStringType()),
                    IrName("item", int64),
                ),
                dict_type,
            ),
        )

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
            _none_guard_name(_owned_parse("None is value").body[0].value),
            "value",
        )
        self.assertIsNone(_none_guard_name(_owned_parse("None is 1").body[0].value))

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

    def test_lowers_ellipsis_stub_function_as_bodyless_signature(self) -> None:
        module = lower_source_to_ir(
            "def declared(value: int) -> int: ...\n",
            filename="ellipsis_stub.py",
            entry="declared",
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrIntType(64, signed=True))
        self.assertEqual(function.return_type, IrRecordType("int | None"))
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

    def test_lowers_string_strip_method_calls(self) -> None:
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

        whitespace = IrConstString(" \t\n\r\v\f")
        for method, target in (
            ("lstrip", "__str_lstrip"),
            ("rstrip", "__str_rstrip"),
            ("strip", "__str_strip"),
        ):
            with self.subTest(method=method):
                module = lower_source_to_ir(
                    "def trim(text: str) -> str:\n"
                    f"    return text.{method}()\n",
                    filename=f"{method}_default.py",
                )
                returned = module.functions[0].body[0].value
                self.assertEqual(
                    returned,
                    IrCall(
                        target,
                        (IrName("text", IrStringType()), whitespace),
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

    def test_lowers_equality_compare_arithmetic_operand_as_integer(self) -> None:
        module = lower_source_to_ir(
            "def at_end(s: str, i: int) -> bool:\n"
            "    return i + 2 == len(s)\n",
            filename="compare_arithmetic_eq.py",
        )
        int64 = IrIntType(64, signed=True)
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__cmp_Eq",
                (
                    IrBinary(
                        "+",
                        IrName("i", int64),
                        IrConstInt(2, int64),
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
                        IrCall("len", (IrName("data", IrBytesType()),), int64),
                        int64,
                    ),
                ),
                IrBytesType(),
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

    def test_value_or_empty_tuple_keeps_tuple_type_when_function_returns_int(self) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "def choose(values: tuple[tuple[int, Type], ...]) -> int:\n"
            "    overrides = values or ()\n"
            "    return 0\n",
            filename="tuple_or_empty_int_fallback.py",
            entry="choose",
        )
        int64 = IrIntType(64, signed=True)
        values_type = IrTupleType((IrTupleType((int64, IrRecordType("Type"))),))
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__ifexp")
        self.assertEqual(assigned.value.type, values_type)

    def test_value_or_empty_dict_keeps_dict_type_when_function_returns_int(self) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "def choose(values: dict[int, Type] | None) -> int:\n"
            "    overrides = values or {}\n"
            "    return 0\n",
            filename="dict_or_empty_int_fallback.py",
            entry="choose",
        )
        values_type = IrDictType(IrIntType(64, signed=True), IrRecordType("Type"))
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__ifexp")
        self.assertEqual(assigned.value.type, values_type)

    def test_uses_extra_global_annotation_for_imported_record_constant(self) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "def choose(value: Type | None) -> Type:\n"
            "    return value or INT\n",
            filename="imported_type_constant.py",
            entry="choose",
            extra_global_annotations={"INT": "Type"},
        )
        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertEqual(
            returned.value,
            IrCall(
                "__ifexp",
                (
                    IrName("value", IrRecordType("Type | None")),
                    IrName("value", IrRecordType("Type | None")),
                    IrName("INT", IrRecordType("Type")),
                ),
                IrRecordType("Type"),
            ),
        )

    def test_value_or_imported_record_constant_ignores_integer_function_fallback(
        self,
    ) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "def choose(value: Type | None) -> int:\n"
            "    result = value or INT\n"
            "    return 0\n",
            filename="imported_type_constant_int_fallback.py",
            entry="choose",
            extra_global_annotations={"INT": "Type"},
        )
        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__ifexp")
        self.assertEqual(assigned.value.type, IrRecordType("Type | None"))

    def test_infers_optional_record_ifexp_assignment_when_function_returns_optional_int(
        self,
    ) -> None:
        module = lower_source_to_ir(
            "class Type:\n"
            "    pass\n"
            "class Expr:\n"
            "    pass\n"
            "class TypeMap:\n"
            "    def get(self, node: Expr) -> Type | None:\n"
            "        return None\n"
            "class Gen:\n"
            "    _type_map: TypeMap\n"
            "    def _resolve_type(self, spec: Expr) -> Type:\n"
            "        return Type()\n"
            "    def choose(\n"
            "        self, has_spec: bool, has_expr: bool, spec: Expr, expr: Expr\n"
            "    ) -> int | None:\n"
            "        result_t = (\n"
            "            self._resolve_type(spec)\n"
            "            if has_spec\n"
            "            else self._type_map.get(expr) if has_expr else None\n"
            "        )\n"
            "        return None if result_t is None else 1\n",
            filename="optional_record_ifexp_assignment.py",
            entry="Gen.choose",
        )
        function = next(function for function in module.functions if function.name == "Gen.choose")
        assigned = function.body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__ifexp")
        self.assertEqual(assigned.value.type, IrRecordType("Type | None"))
        self.assertEqual(function.return_type, IrIntType(64, signed=True))

    def test_ifexp_narrows_optional_record_in_none_test_else_branch(self) -> None:
        module = lower_source_to_ir(
            "class Token:\n"
            "    kind: str\n"
            "class Parser:\n"
            "    def current(self) -> Token:\n"
            "        return Token('EOF')\n"
            "    def choose(self, token: Token | None = None) -> Token:\n"
            "        culprit = self.current() if token is None else token\n"
            "        return culprit\n",
            filename="ifexp_none_else.py",
            entry="Parser.choose",
        )
        function = next(function for function in module.functions if function.name == "Parser.choose")
        assigned = function.body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.type, IrRecordType("Token"))
        self.assertEqual(assigned.value.args[2], IrName("token", IrRecordType("Token")))

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
            IrAssign(
                "ch",
                IrCall("Scanner._peek", (scanner, IrConstInt(0, int64)), IrStringType()),
            ),
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
            ("def f(text: str) -> str:\n    return text.rstrip('x', 'y')\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> str:\n    return value.rstrip('x')\n", "XCC-AOT-LOWER-0003"),
            ("def f(text: str) -> str:\n    return text.lstrip(chars='x')\n", "XCC-AOT-LOWER-0003"),
            ("def f(value: int) -> str:\n    return value.strip('x')\n", "XCC-AOT-LOWER-0003"),
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
                "    return enumerate(values, 1, 2)\n",
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
                "    return list(values, 1)\n",
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
            ("def f(value: str) -> list[str]:\n    return value.split(sep='.')\n", "XCC-AOT-LOWER-0003"),
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
        bad_call = _owned_parse("llvm()", mode="eval").body
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
            _llvm_api_call_return_type("AddCase", IrIntType(64, signed=True)),
            IrNoneType(),
        )
        self.assertEqual(
            _llvm_api_call_return_type("AddIncoming", IrIntType(64, signed=True)),
            IrNoneType(),
        )
        self.assertEqual(
            _llvm_api_call_return_type("SetAlignment", IrIntType(64, signed=True)),
            IrNoneType(),
        )
        self.assertEqual(
            _llvm_api_call_return_type("IsNull", IrIntType(64, signed=True)),
            IrBoolType(),
        )
        self.assertEqual(
            _llvm_api_call_return_type("GetTypeKind", IrTupleType((IrIntType(64, True),))),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("Int8Type", IrRecordType("object")),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("CreateBuilder", IrRecordType("Builder")),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("CreateBuilder", IrNoneType()),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("GetBasicBlockTerminator", IrBoolType()),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("ConstIntGetSExtValue", IrRecordType("object")),
            IrIntType(64, signed=True),
        )
        self.assertEqual(
            _llvm_api_call_return_type("ConstIntGetZExtValue", IrRecordType("object")),
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
        missing_param = _owned_parse("def f(value) -> int:\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(missing_param, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")

        missing_return = _owned_parse("def f():\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(missing_return, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].message, "Missing lowered annotation")

        unsupported_return = _owned_parse("def f() -> float:\n    return 1\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_return, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

        unsupported_string_return = _owned_parse('def f() -> "int":\n    return 1\n').body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_string_return, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

        unsupported_call = _owned_parse("def f(value: int) -> int:\n    return value.bits()\n").body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_call, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0003")

        unsupported_dynamic_call = _hosted_owned_parse(
            "def f() -> int:\n    return (lambda: 1)()\n"
        ).body[0]
        with self.assertRaises(AotError) as ctx:
            lowerer.lower_function(unsupported_dynamic_call, owner=None)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0003")

        with self.assertRaises(AotError) as ctx:
            lowerer._lower_statement(
                _hosted_owned_parse("del value\n").body[0],
                {},
                IrNoneType(),
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")

        with self.assertRaises(AotError) as ctx:
            lowerer._lower_expr(
                _owned_parse("lambda: 1", mode="eval").body,
                {},
                IrRecordType("object"),
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

        missing_kwonly = _owned_parse("def f(*, flag) -> int:\n    return 1\n").body[0]
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

        structured_try = _owned_parse(
            "def f() -> int:\n"
            "    try:\n"
            "        return 1\n"
            "    except RuntimeError:\n"
            "        return 0\n"
        ).body[0]
        lowered_try = lowerer.lower_function(structured_try, owner=None).body[0]
        self.assertIsInstance(lowered_try, IrTry)
        assert isinstance(lowered_try, IrTry)
        self.assertEqual(
            lowered_try.handlers,
            (
                IrExceptHandler(
                    ("RuntimeError",),
                    None,
                    lowered_try.handlers[0].body,
                ),
            ),
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
        record = lowerer.lower_record(_owned_parse("class Node:\n    pass\n").body[0])
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
            IrDictType(
                IrStringType(),
                IrTupleType((IrStringType(), IrRecordType("object"))),
            ),
        )
        self.assertIsNone(lowerer._optional_record_inner(IrIntType(64, signed=True)))
        self.assertEqual(lowerer._aot_type_to_ir_type(AotType("NoReturn")), IrNoneType())
        self.assertEqual(lowerer._aot_type_to_ir_type(AotType("object")), IrRecordType("object"))
        with self.assertRaises(AotError) as ctx:
            lowerer._record_field_type(IrIntType(64, signed=True), "value", ast.Pass())
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")

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

    def test_lowers_callable_annotations_as_opaque_object(self) -> None:
        module = lower_source_to_ir(
            "from typing import Callable\n"
            "def echo(callback: Callable[[str], int]) -> Callable[[str], int]:\n"
            "    return callback\n",
            filename="callable.py",
            entry="echo",
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrRecordType("object"))
        self.assertEqual(function.return_type, IrRecordType("object"))

    def test_specializes_callable_parameter_call_to_default_target(self) -> None:
        module = lower_source_to_ir(
            "from typing import Callable\n"
            "def parse(text: str) -> str:\n"
            "    return text\n"
            "def use(text: str, parser: Callable[[str], str] = parse) -> str:\n"
            "    return parser(text)\n",
            filename="callable_default.py",
            entry="use",
        )
        returned = module.functions[1].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "parse",
                (IrName("text", IrStringType()),),
                IrStringType(),
            ),
        )

        caller = lower_source_to_ir(
            "from typing import Callable\n"
            "def parse(text: str) -> str:\n"
            "    return text\n"
            "def use(text: str, parser: Callable[[str], str] = parse) -> str:\n"
            "    return parser(text)\n"
            "def entry(text: str) -> str:\n"
            "    return use(text, parse)\n",
            filename="callable_default_arg.py",
            entry="entry",
        )
        self.assertEqual(
            caller.functions[2].body[0].value,
            IrCall(
                "use",
                (IrName("text", IrStringType()), IrConstNone()),
                IrStringType(),
            ),
        )

    def test_specializes_callable_default_to_unique_qualified_target(self) -> None:
        module = lower_source_to_ir(
            "from typing import Callable\n"
            "def use(text: str, parser: Callable[[str], tuple[str, str] | None] = _parse) -> tuple[str, str] | None:\n"
            "    parsed = None if text == '' else parser(text)\n"
            "    return parsed\n",
            filename="callable_qualified_default.py",
            entry="use",
            extra_functions={
                "pkg._parse": AotFunctionInfo(
                    "pkg._parse",
                    (("text", "str"),),
                    AotType("tuple[str, str] | None"),
                ),
            },
        )
        assigned = module.functions[0].body[0].value
        self.assertEqual(
            assigned,
            IrCall(
                "__ifexp",
                (
                    IrCall(
                        "__cmp_Eq",
                        (IrName("text", IrStringType()), IrConstString("")),
                        IrBoolType(),
                    ),
                    IrConstNone(),
                    IrCall(
                        "pkg._parse",
                        (IrName("text", IrStringType()),),
                        IrTupleType((IrStringType(), IrStringType())),
                    ),
                ),
                IrTupleType((IrStringType(), IrStringType())),
            ),
        )
        returned = module.functions[0].body[1].value
        self.assertEqual(returned, IrName("parsed", IrTupleType((IrStringType(), IrStringType()))))

    def test_lowers_object_annotations_as_opaque_object(self) -> None:
        module = lower_source_to_ir(
            "def echo(value: object) -> object:\n"
            "    return value\n",
            filename="object.py",
            entry="echo",
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrRecordType("object"))
        self.assertEqual(function.return_type, IrRecordType("object"))

    def test_lowers_path_parent_property_as_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def parent(path: Path) -> Path:\n"
            "    return path.parent\n",
            filename="path_parent.py",
            entry="parent",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall("__path_parent", (IrName("path", IrRecordType("Path")),), IrRecordType("Path")),
        )

    def test_lowers_path_join_operator_as_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def join(path: Path, child: str) -> Path:\n"
            "    return path / child\n",
            filename="path_join.py",
            entry="join",
        )
        returned = module.functions[0].body[0].value
        path_type = IrRecordType("Path")
        self.assertEqual(
            returned,
            IrCall(
                "__path_join",
                (IrName("path", path_type), IrName("child", IrStringType())),
                path_type,
            ),
        )

    def test_lowers_path_name_property_as_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def name(path: Path) -> str:\n"
            "    return path.name\n",
            filename="path_name.py",
            entry="name",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall("__path_name", (IrName("path", IrRecordType("Path")),), IrStringType()),
        )

    def test_lowers_path_constructor_resolve_and_str_as_intrinsics(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def resolved(filename: str) -> str:\n"
            "    return str(Path(filename).resolve())\n",
            filename="path_resolve.py",
            entry="resolved",
        )
        returned = module.functions[0].body[0].value
        path_type = IrRecordType("Path")
        self.assertEqual(
            returned,
            IrCall(
                "__path_to_string",
                (
                    IrCall(
                        "__path_resolve",
                        (
                            IrCall(
                                "__path_from_string",
                                (IrName("filename", IrStringType()),),
                                path_type,
                            ),
                        ),
                        path_type,
                    ),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_optional_string_str_call_as_identity(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Token:\n"
            "    lexeme: str | None\n"
            "def text(token: Token) -> str:\n"
            "    return str(token.lexeme)\n",
            filename="optional_string_str.py",
            entry="text",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__path_to_string",
                (
                    IrGetField(
                        IrName("token", IrRecordType("Token")),
                        "lexeme",
                        IrRecordType("str | None"),
                    ),
                ),
                IrStringType(),
            ),
        )

    def test_lowers_int_str_call_as_string_concat_coercion(self) -> None:
        module = lower_source_to_ir(
            "def text(value: int) -> str:\n"
            "    return str(value)\n",
            filename="int_str.py",
            entry="text",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrStringConcat((IrName("value", IrIntType(64, signed=True)),)),
        )

    def test_lowers_record_str_call_as_dunder_str_method(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "    def __str__(self) -> str:\n"
            "        return self.name\n"
            "def text(value: Type) -> str:\n"
            "    return str(value)\n",
            filename="record_str.py",
            entry="text",
        )
        returned = module.functions[1].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "Type.__str__",
                (IrName("value", IrRecordType("Type")),),
                IrStringType(),
            ),
        )

    def test_lowers_optional_string_method_receiver_as_string_identity(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Token:\n"
            "    lexeme: str | None\n"
            "def has_suffix(token: Token, suffix: str) -> bool:\n"
            "    return token.lexeme.endswith(suffix)\n",
            filename="optional_string_method.py",
            entry="has_suffix",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__str_endswith",
                (
                    IrCall(
                        "__path_to_string",
                        (
                            IrGetField(
                                IrName("token", IrRecordType("Token")),
                                "lexeme",
                                IrRecordType("str | None"),
                            ),
                        ),
                        IrStringType(),
                    ),
                    IrName("suffix", IrStringType()),
                ),
                IrBoolType(),
            ),
        )

    def test_lowers_optional_path_resolve_as_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def resolved(path: Path | None) -> Path:\n"
            "    return path.resolve()\n",
            filename="path_optional_resolve.py",
            entry="resolved",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall(
                "__path_resolve",
                (IrName("path", IrRecordType("Path | None")),),
                IrRecordType("Path"),
            ),
        )

    def test_lowers_path_read_text_as_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def read(path: Path) -> str:\n"
            "    return path.read_text(encoding='utf-8', errors='surrogateescape')\n",
            filename="path_read_text.py",
            entry="read",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall("__path_read_text", (IrName("path", IrRecordType("Path")),), IrStringType()),
        )

    def test_lowers_path_is_file_as_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "from pathlib import Path\n"
            "def exists(path: Path) -> bool:\n"
            "    return path.is_file()\n",
            filename="path_is_file.py",
            entry="exists",
        )
        returned = module.functions[0].body[0].value
        self.assertEqual(
            returned,
            IrCall("__path_is_file", (IrName("path", IrRecordType("Path")),), IrBoolType()),
        )

    def test_lowers_typing_cast_as_identity_with_target_type(self) -> None:
        module = lower_source_to_ir(
            "from typing import Any, cast\n"
            "class Box:\n"
            "    pass\n"
            "def echo(value: Any) -> Box:\n"
            "    boxed = cast(Box, value)\n"
            "    return boxed\n",
            filename="cast_identity.py",
            include_records={"Box"},
            entry="echo",
        )
        assigned = module.functions[0].body[0]
        self.assertEqual(assigned, IrAssign("boxed", IrName("value", IrRecordType("Box"))))

    def test_lowers_bytes_annotations_as_bytes_type(self) -> None:
        module = lower_source_to_ir(
            "def echo(value: bytes) -> bytes:\n"
            "    return value\n",
            filename="bytes.py",
            entry="echo",
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrBytesType())
        self.assertEqual(function.return_type, IrBytesType())

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
                IrBytesType(),
            ),
        )

    def test_lowers_bytes_concat_and_repeat_intrinsics(self) -> None:
        module = lower_source_to_ir(
            "def combine(value: bytes, count: int) -> bytes:\n"
            "    value += b'x' * count\n"
            "    return value + b'y'\n",
            filename="bytes_ops.py",
            entry="combine",
        )
        function = module.functions[0]
        assigned = function.body[0]
        self.assertIsInstance(assigned, IrAssign)
        assert isinstance(assigned, IrAssign)
        self.assertIsInstance(assigned.value, IrCall)
        assert isinstance(assigned.value, IrCall)
        self.assertEqual(assigned.value.target, "__bytes_concat")
        repeated = assigned.value.args[1]
        self.assertIsInstance(repeated, IrCall)
        assert isinstance(repeated, IrCall)
        self.assertEqual(repeated.target, "__bytes_repeat")
        returned = function.body[1]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__bytes_concat")

    def test_lowers_bytes_for_each_target_as_integer(self) -> None:
        module = lower_source_to_ir(
            "def total(data: bytes) -> int:\n"
            "    result = 0\n"
            "    for byte in data:\n"
            "        result += byte\n"
            "    return result\n",
            filename="bytes_for.py",
            entry="total",
        )
        loop = module.functions[0].body[1]
        self.assertIsInstance(loop, IrForEach)
        assert isinstance(loop, IrForEach)
        updated = loop.body.statements[0]
        self.assertIsInstance(updated, IrAssign)
        assert isinstance(updated, IrAssign)
        self.assertIsInstance(updated.value, IrBinary)
        assert isinstance(updated.value, IrBinary)
        self.assertEqual(updated.value.right.type, IrIntType(64, signed=True))

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
            "    return value.to_bytes(size, 'little', signed=False)\n",
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
                IrBytesType(),
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
                _owned_parse("isinstance(value.attr, Child)", mode="eval").body,
                {"value": IrRecordType("object")},
            )
        )
        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                _owned_parse("isinstance(value, Missing)", mode="eval").body,
                {"value": IrRecordType("object")},
            )
        )
        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                _owned_parse("isinstance(value, Child)", mode="eval").body,
                {"value": IrIntType(64, signed=True)},
            )
        )
        self.assertIsNone(
            lowerer._isinstance_guard_narrowing(
                _owned_parse("isinstance(value, (Child, 1))", mode="eval").body,
                {"value": IrRecordType("object")},
            )
        )
        self.assertEqual(
            lowerer._isinstance_guard_narrowing(
                _owned_parse("isinstance(value, (Child, Base))", mode="eval").body,
                {"value": IrRecordType("object")},
            ),
            ("value", IrRecordType("Child | Base")),
        )
        self.assertEqual(
            _isinstance_target_names(_owned_parse("(Child, Base)", mode="eval").body),
            ("Child", "Base"),
        )
        self.assertIsNone(_isinstance_target_names(_owned_parse("(Child, 1)", mode="eval").body))
        self.assertIsNone(_isinstance_target_names(_owned_parse("factory()", mode="eval").body))

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
                _owned_parse("None is not value", mode="eval").body,
                {"value": IrRecordType("Child | None")},
            ),
            ("value", IrRecordType("Child")),
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(_owned_parse("None is not 1", mode="eval").body, {})
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(_owned_parse("1 is not 2", mode="eval").body, {})
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(
                _owned_parse("missing is not None", mode="eval").body,
                {},
            )
        )
        self.assertIsNone(
            lowerer._not_none_guard_narrowing(
                _owned_parse("value is not None", mode="eval").body,
                {"value": IrIntType(64, signed=True)},
            )
        )
        self.assertIsNone(
            lowerer._none_bool_op_narrowing(
                _owned_parse("value is None", mode="eval").body,
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
        target = _owned_parse("self.value = 1\n").body[0].targets[0]
        lowerer._bind_assignment_target(target, IrIntType(64, signed=True), names)
        self.assertIn("self.value", names)
        unsupported_target = _owned_parse("items[0] = 1\n").body[0].targets[0]
        with self.assertRaises(AotError) as ctx:
            lowerer._bind_assignment_target(
                unsupported_target,
                IrIntType(64, signed=True),
                names,
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0001")
        tree = _owned_parse(
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
                _owned_parse("''.join()\n").body[0].value,
                {},
                IrStringType(),
            ),
            IrStringJoin,
        )
        int64 = IrIntType(64, signed=True)
        fallback = IrRecordType("object")
        field_target = _owned_parse("value.field = None\n").body[0].targets[0]
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
                _owned_parse("missing[0]", mode="eval").body,
                {},
                fallback,
            ),
            fallback,
        )
        mixed_ifexp = _owned_parse("1 if flag else 'x'").body[0].value
        self.assertEqual(
            lowerer._infer_assignment_expr_type(mixed_ifexp, {"flag": IrBoolType()}, fallback),
            fallback,
        )
        mixed_bool = _owned_parse("text or flag", mode="eval").body
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
                _owned_parse("not flag", mode="eval").body,
                {"flag": IrBoolType()},
                fallback,
            ),
            IrBoolType(),
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                _owned_parse("left + right", mode="eval").body,
                {"left": IrStringType(), "right": IrStringType()},
                fallback,
            ),
            IrStringType(),
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                _owned_parse("left - right", mode="eval").body,
                {"left": IrStringType(), "right": IrStringType()},
                fallback,
            ),
            fallback,
        )
        self.assertEqual(
            lowerer._infer_assignment_expr_type(
                _owned_parse("value.missing", mode="eval").body,
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
            _tuple_subscript_result_type(_owned_parse("-1", mode="eval").body, fixed_tuple_type),
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
            (IrStringType(), IrRecordType("object")),
        )
        self.assertEqual(
            lowerer._tuple_backed_container_types("dict[str, object]", ast.Pass()),
            (IrStringType(), IrRecordType("object")),
        )
        self.assertEqual(
            lowerer._tuple_backed_container_types("list[object]", ast.Pass()),
            (IrRecordType("object"),),
        )
        self.assertEqual(lowerer._optional_container_type("object", ast.Pass()), fallback)
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

    def test_exception_constructor_maps_init_parameters_to_payload_fields(self) -> None:
        source = (
            "class Problem(ValueError):\n"
            "    def __init__(\n"
            "        self, message: str, line: int | None = None, *, code: str = 'E'\n"
            "    ) -> None:\n"
            "        self.line = line\n"
            "        self.code = code\n"
            "def fail() -> None:\n"
            "    raise Problem('bad', 7, code='X')\n"
        )
        module = lower_source_to_ir(source, filename="exception_payload_fields.py", entry="fail")

        raised = next(function for function in module.functions if function.name == "fail").body[0]
        self.assertIsInstance(raised, IrRaise)
        assert isinstance(raised, IrRaise)
        self.assertIsInstance(raised.payload, IrConstructRecord)
        assert isinstance(raised.payload, IrConstructRecord)
        self.assertEqual(
            raised.payload.args,
            (
                IrConstInt(7, IrIntType(64, signed=True)),
                IrConstString("X"),
            ),
        )

    def test_raise_factory_uses_returned_exception_record_type(self) -> None:
        module = lower_source_to_ir(
            "class Problem(ValueError):\n"
            "    pass\n"
            "def make_problem() -> Problem:\n"
            "    return Problem()\n"
            "def fail() -> None:\n"
            "    raise make_problem()\n",
            filename="raise_factory.py",
            entry="fail",
        )
        raised = next(function for function in module.functions if function.name == "fail").body[0]
        self.assertIsInstance(raised, IrRaise)
        assert isinstance(raised, IrRaise)
        self.assertEqual(raised.exception, "Problem")
        self.assertEqual(
            raised.payload,
            IrCall("make_problem", (), IrRecordType("Problem")),
        )

    def test_lowers_missing_concrete_record_field_as_nested_default_constructor(self) -> None:
        source = (
            "int64 = int\n"
            "class LineMap:\n"
            "    entries: list[tuple[str, int64]]\n"
            "class Builder:\n"
            "    chunks: list[str]\n"
            "    line_map: LineMap\n"
            "def entry() -> Builder:\n"
            "    return Builder()\n"
        )
        module = lower_source_to_ir(source, filename="nested_record_default.py", entry="entry")

        entry = next(function for function in module.functions if function.name == "entry")
        returned = entry.body[0].value

        self.assertIsInstance(returned, IrConstructRecord)
        self.assertEqual(returned.record, "Builder")
        self.assertIsInstance(returned.args[0], IrTuple)
        line_map = returned.args[1]
        self.assertIsInstance(line_map, IrConstructRecord)
        self.assertEqual(line_map.record, "LineMap")
        self.assertIsInstance(line_map.args[0], IrTuple)

    def test_lowers_keyword_call_arguments_in_signature_order(self) -> None:
        source = (
            "def update(\n"
            "    active: bool,\n"
            "    from_directive: bool,\n"
            "    *,\n"
            "    directive_lines: list[str] | None = None,\n"
            "    line: str | None = None,\n"
            ") -> bool:\n"
            "    return active\n"
            "def entry() -> bool:\n"
            "    return update(False, False, line='x')\n"
        )
        module = lower_source_to_ir(source, filename="keyword_call_order.py", entry="entry")

        entry = next(function for function in module.functions if function.name == "entry")
        returned = entry.body[0].value

        self.assertIsInstance(returned, IrCall)
        self.assertEqual(len(returned.args), 4)
        self.assertIsInstance(returned.args[2], IrConstNone)
        self.assertEqual(returned.args[3], IrConstString("x"))

    def test_lowers_lexer_constructor_with_runtime_field_defaults(self) -> None:
        source = (
            "int64 = int\n"
            "class Lexer:\n"
            "    _source: str\n"
            "    _length: int64\n"
            "    _index: int64\n"
            "    _line: int64\n"
            "    _column: int64\n"
            "    _mode: str\n"
            "    _header_names: bool\n"
            "def translate_source(source: str) -> str:\n"
            "    return source\n"
            "def make(source: str) -> Lexer:\n"
            "    return Lexer(source)\n"
        )
        module = lower_source_to_ir(source, filename="lexer_constructor.py", entry="make")

        make = next(function for function in module.functions if function.name == "make")
        returned = make.body[0].value

        self.assertIsInstance(returned, IrConstructRecord)
        self.assertEqual(returned.record, "Lexer")
        self.assertEqual(len(returned.args), 7)
        self.assertEqual(returned.args[0], IrCall("translate_source", (IrName("source", IrStringType()),), IrStringType()))
        self.assertEqual(returned.args[1], IrCall("len", (returned.args[0],), IrIntType(64, signed=True)))
        self.assertEqual(returned.args[2], IrConstInt(0, IrIntType(64, signed=True)))
        self.assertEqual(returned.args[3], IrConstInt(1, IrIntType(64, signed=True)))
        self.assertEqual(returned.args[4], IrConstInt(1, IrIntType(64, signed=True)))
        self.assertEqual(returned.args[5], IrConstString("translation"))
        self.assertEqual(returned.args[6], IrConstBool(False))

    def test_lowers_parser_constructor_with_initial_scope_stacks(self) -> None:
        source = (
            "int64 = int\n"
            "class Token:\n"
            "    lexeme: str | None\n"
            "class TypeSpec:\n"
            "    name: str\n"
            "class Param:\n"
            "    name: str | None\n"
            "class Parser:\n"
            "    _tokens: list[Token]\n"
            "    _index: int64\n"
            "    _std: str\n"
            "    _typedef_scopes: list[dict[str, TypeSpec]]\n"
            "    _typedef_qualified_scopes: list[dict[str, bool]]\n"
            "    _ordinary_name_scopes: list[set[str]]\n"
            "    _ordinary_type_scopes: list[dict[str, TypeSpec]]\n"
            "    _ordinary_value_scopes: list[dict[str, int64]]\n"
            "    _capture_next_fn_params: bool\n"
            "    _has_function_def_info: bool\n"
            "    _function_def_params: list[Param]\n"
            "    _function_def_has_prototype: bool\n"
            "    _function_def_is_variadic: bool\n"
            "def make(tokens: list[Token]) -> Parser:\n"
            "    return Parser(tokens, std='gnu11')\n"
        )
        module = lower_source_to_ir(source, filename="parser_constructor.py", entry="make")

        make = next(function for function in module.functions if function.name == "make")
        returned = make.body[0].value

        self.assertIsInstance(returned, IrConstructRecord)
        self.assertEqual(returned.record, "Parser")
        self.assertEqual(returned.args[2], IrConstString("gnu11"))
        for index in range(3, 8):
            scope_stack = returned.args[index]
            self.assertIsInstance(scope_stack, IrTuple)
            assert isinstance(scope_stack, IrTuple)
            self.assertEqual(len(scope_stack.elements), 1)
            self.assertIsInstance(scope_stack.elements[0], IrTuple)
        self.assertEqual(returned.args[10], IrTuple((), IrTupleType((IrRecordType("Param"),))))

    def test_lowers_directive_cursor_constructor_with_location_tuple(self) -> None:
        int64 = IrIntType(64, signed=True)
        source = (
            "class _SourceLocation:\n"
            "    filename: str\n"
            "    line: int\n"
            "class _LogicalCursor:\n"
            "    filename: str\n"
            "    line: int\n"
            "def _directive_cursor_locations(\n"
            "    cursor: _LogicalCursor,\n"
            "    count: int,\n"
            ") -> tuple[_SourceLocation, ...]:\n"
            "    return ()\n"
            "class _DirectiveCursor:\n"
            "    _locations: tuple[_SourceLocation, ...]\n"
            "def make(cursor: _LogicalCursor, count: int) -> _DirectiveCursor:\n"
            "    return _DirectiveCursor(cursor, count)\n"
        )
        module = lower_source_to_ir(
            source,
            filename="directive_cursor_constructor.py",
            entry="make",
        )

        make = next(function for function in module.functions if function.name == "make")
        returned = make.body[0].value

        self.assertIsInstance(returned, IrConstructRecord)
        assert isinstance(returned, IrConstructRecord)
        self.assertEqual(returned.record, "_DirectiveCursor")
        self.assertEqual(
            returned.args,
            (
                IrCall(
                    "_directive_cursor_locations",
                    (
                        IrName("cursor", IrRecordType("_LogicalCursor")),
                        IrName("count", int64),
                    ),
                    IrTupleType((IrRecordType("_SourceLocation"),)),
                ),
            ),
        )

    def test_lowers_llvmgen_constructor_with_runtime_handles(self) -> None:
        int64 = IrIntType(64, signed=True)
        source = (
            "int64 = int\n"
            "class TranslationUnit:\n"
            "    filename: str\n"
            "class TypeMap:\n"
            "    size: int64\n"
            "class SemaUnit:\n"
            "    type_map: TypeMap\n"
            "class FrontendResult:\n"
            "    filename: str\n"
            "    unit: TranslationUnit\n"
            "    sema: SemaUnit\n"
            "class FunctionSymbol:\n"
            "    name: str\n"
            "class _LoopCtx:\n"
            "    continue_block: int64\n"
            "    break_block: int64\n"
            "class _LLVMGen:\n"
            "    _result: FrontendResult\n"
            "    _unit: TranslationUnit\n"
            "    _type_map: TypeMap\n"
            "    _sema: SemaUnit\n"
            "    _ctx: int64\n"
            "    _mod: int64\n"
            "    _builder: int64\n"
            "    _str_constants: dict[str, int64]\n"
            "    _compound_literal_globals: dict[int64, int64]\n"
            "    _func_types: dict[str, int64]\n"
            "    _func_param_types: dict[str, list[int64]]\n"
            "    _struct_types: dict[str, int64]\n"
            "    _static_local_counter: int64\n"
            "    _static_local_globals: dict[int64, int64]\n"
            "    _static_local_global_values: set[int64]\n"
            "    _func: int64\n"
            "    _func_sym: FunctionSymbol | None\n"
            "    _locals: list[dict[str, int64]]\n"
            "    _label_blocks: dict[str, int64]\n"
            "    _loop_stack: list[_LoopCtx]\n"
            "    _break_stack: list[int64]\n"
            "    _switch_info: list[tuple[int64, int64, int64 | None, bool, int64]]\n"
            "    _entry_block: int64\n"
            "def make(result: FrontendResult) -> _LLVMGen:\n"
            "    return _LLVMGen(result)\n"
        )
        module = lower_source_to_ir(source, filename="llvmgen_constructor.py", entry="make")

        make = next(function for function in module.functions if function.name == "make")
        returned = make.body[0].value

        self.assertIsInstance(returned, IrConstructRecord)
        assert isinstance(returned, IrConstructRecord)
        result = IrName("result", IrRecordType("FrontendResult"))
        sema = IrGetField(result, "sema", IrRecordType("SemaUnit"))
        self.assertEqual(returned.record, "_LLVMGen")
        self.assertEqual(returned.args[0], result)
        self.assertEqual(
            returned.args[1],
            IrGetField(result, "unit", IrRecordType("TranslationUnit")),
        )
        self.assertEqual(returned.args[2], IrGetField(sema, "type_map", IrRecordType("TypeMap")))
        self.assertEqual(returned.args[3], sema)
        self.assertEqual(returned.args[4], IrCall("__llvm_ContextCreate", (), int64))
        self.assertEqual(
            returned.args[5],
            IrCall(
                "__llvm_ModuleCreateWithName",
                (IrGetField(result, "filename", IrStringType()),),
                int64,
            ),
        )
        self.assertEqual(returned.args[6], IrCall("__llvm_CreateBuilder", (), int64))


if __name__ == "__main__":
    unittest.main()
