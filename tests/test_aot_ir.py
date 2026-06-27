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
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrEnumMember,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRaise,
    IrRecordType,
    IrReturn,
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
    _collect_global_names,
    _dict_container_type_names,
    _dict_get_result_type,
    _Lowerer,
    _none_guard_name,
    _tuple_backed_container_element_name,
)
from xcc.aot.module import parse_source
from xcc.aot.subset import check_subset
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
            ("def f() -> int:\n    return int()\n", "XCC-AOT-LOWER-0003"),
            ("def f() -> int:\n    return int('1', base=10)\n", "XCC-AOT-LOWER-0003"),
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
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("tuple[Node, ...]")),
            IrTupleType((IrRecordType("Node"),)),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("tuple[TypeOp, ...]")),
            IrTupleType(()),
        )
        self.assertEqual(
            lowerer._aot_type_to_ir_type(AotType("dict[str, TypeOp]")),
            IrTupleType(()),
        )
        self.assertIsNone(lowerer._optional_record_inner(IrIntType(64, signed=True)))
        self.assertEqual(lowerer._aot_type_to_ir_type(AotType("NoReturn")), IrNoneType())
        with self.assertRaises(AotError) as ctx:
            lowerer._record_field_type(IrIntType(64, signed=True), "value", ast.Pass())
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LOWER-0002")
        with self.assertRaises(AotError) as ctx:
            lowerer._aot_type_to_ir_type(AotType("object"))
        self.assertEqual(ctx.exception.diagnostics[0].message, "Unsupported lowered type: object")

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
            lowerer._infer_assignment_expr_type(ast.Constant(1.5), {}, fallback),
            fallback,
        )
        mixed_ifexp = ast.parse("1 if flag else 'x'").body[0].value
        self.assertEqual(
            lowerer._infer_assignment_expr_type(mixed_ifexp, {"flag": IrBoolType()}, fallback),
            fallback,
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
