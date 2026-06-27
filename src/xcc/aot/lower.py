import ast
from typing import Literal, NoReturn

from xcc.aot.analysis import analyze_source
from xcc.aot.diag import AotDiagnostic, AotError, node_location
from xcc.aot.ir import (
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
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrEnumMember,
    IrExpr,
    IrField,
    IrFloatType,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRaise,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrSetItem,
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrType,
    IrWhile,
)
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType, annotation_name

_ALLOWED_BUILTIN_CALLS = {
    "bool",
    "isinstance",
    "len",
    "range",
    "reversed",
    "str",
    "sum",
    "super",
    "tuple",
}
_ALLOWED_BUILTIN_VALUES = {"bool", "int", "object", "str", "tuple"}
_ALLOWED_MUTATING_TUPLE_CALLS = {"append", "extend", "pop"}
_STRING_PREDICATE_METHODS = frozenset({"isalpha", "isdigit", "isalnum", "isspace"})
_LLVM_API_RECORD = "LLVMApi"


def lower_source_to_ir(
    source: str,
    *,
    filename: str = "<input>",
    entry: str | None = None,
    include_records: set[str] | frozenset[str] | None = None,
    include_functions: set[str] | frozenset[str] | None = None,
    bodyless_functions: set[str] | frozenset[str] | None = None,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> IrModule:
    analysis = analyze_source(source, filename=filename)
    class_types = dict(extra_classes or {})
    class_types.update(analysis.types.classes)
    function_types = dict(extra_functions or {})
    function_types.update(analysis.types.functions)
    lowerer = _Lowerer(
        filename,
        class_types,
        function_types,
        analysis.types.aliases,
        _collect_global_names(analysis.module.tree),
    )
    records = tuple(
        lowerer.lower_record(node)
        for node in analysis.module.tree.body
        if isinstance(node, ast.ClassDef)
        and (include_records is None or node.name in include_records)
    )
    functions: list[IrFunction] = []
    bodyless = bodyless_functions or frozenset()
    for node in analysis.module.tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    function_name = _lowered_function_name(child.name, node.name)
                    if include_functions is None or function_name in include_functions:
                        functions.append(
                            lowerer.lower_function(
                                child,
                                owner=node.name,
                                bodyless=function_name in bodyless,
                            )
                        )
    for node in analysis.module.tree.body:
        if isinstance(node, ast.FunctionDef):
            function_name = _lowered_function_name(node.name, None)
            if include_functions is None or function_name in include_functions:
                functions.append(
                    lowerer.lower_function(
                        node,
                        owner=None,
                        bodyless=function_name in bodyless,
                    )
                )
    return IrModule(filename, records, tuple(functions), entry=entry)


class _Lowerer:
    def __init__(
        self,
        filename: str,
        class_types: dict[str, AotClassInfo],
        function_types: dict[str, AotFunctionInfo] | None = None,
        aliases: dict[str, AotType] | None = None,
        global_names: set[str] | None = None,
    ) -> None:
        self.filename = filename
        self.class_types = class_types
        self.function_types = function_types or {}
        self.aliases = aliases or {}
        self.global_names = global_names or set()

    def lower_record(self, node: ast.ClassDef) -> IrRecord:
        class_info = self.class_types[node.name]
        fields = tuple(
            IrField(name, self._aot_type_to_ir_type(field_type))
            for name, field_type in class_info.fields.items()
        )
        return IrRecord(node.name, fields)

    def lower_function(
        self,
        node: ast.FunctionDef,
        *,
        owner: str | None,
        bodyless: bool = False,
    ) -> IrFunction:
        function_name = _lowered_function_name(node.name, owner)
        params, names = self._lower_params(node, owner)
        return_type = self._annotation_to_ir_type(node.returns)
        if bodyless:
            return IrFunction(function_name, params, return_type, ())
        body = tuple(
            self._lower_statement(statement, names, return_type) for statement in node.body
        )
        return IrFunction(function_name, params, return_type, body)

    def _lower_params(
        self,
        node: ast.FunctionDef,
        owner: str | None,
    ) -> tuple[tuple[IrParam, ...], dict[str, IrType]]:
        params: list[IrParam] = []
        names: dict[str, IrType] = {}
        args = node.args.posonlyargs + node.args.args
        for index, arg in enumerate(args):
            if owner is not None and index == 0 and arg.annotation is None:
                ir_type: IrType = IrRecordType(owner)
                params.append(IrParam(arg.arg, ir_type))
                names[arg.arg] = ir_type
                continue
            if arg.annotation is None:
                self._error(
                    "XCC-AOT-LOWER-0001",
                    f"Missing lowered parameter annotation: {node.name}.{arg.arg}",
                    arg,
                )
            ir_type = self._annotation_to_ir_type(arg.annotation)
            params.append(IrParam(arg.arg, ir_type))
            names[arg.arg] = ir_type
        for arg in node.args.kwonlyargs:
            if arg.annotation is None:
                self._error(
                    "XCC-AOT-LOWER-0001",
                    f"Missing lowered parameter annotation: {node.name}.{arg.arg}",
                    arg,
                )
            ir_type = self._annotation_to_ir_type(arg.annotation)
            params.append(IrParam(arg.arg, ir_type))
            names[arg.arg] = ir_type
        return tuple(params), names

    def _lower_statement(
        self,
        statement: ast.stmt,
        names: dict[str, IrType],
        return_type: IrType,
    ) -> IrStmt:
        if isinstance(statement, ast.If):
            condition = self._lower_expr(statement.test, names, IrBoolType())
            then_names = dict(names)
            else_names = dict(names)
            narrowed: tuple[str, IrType] | None = (
                self._isinstance_guard_narrowing(
                    statement.test,
                    names,
                )
                or self._not_none_guard_narrowing(
                    statement.test,
                    names,
                )
                or self._truthy_optional_record_narrowing(statement.test, names)
            )
            if narrowed is not None:
                narrowed_name, narrowed_type = narrowed
                then_names[narrowed_name] = narrowed_type
            then_branch = IrBranch(
                tuple(
                    self._lower_statement(child, then_names, return_type)
                    for child in statement.body
                )
            )
            if narrowed is not None and then_names.get(narrowed_name) == narrowed_type:
                if narrowed_name in names:
                    then_names[narrowed_name] = names[narrowed_name]
                else:
                    then_names.pop(narrowed_name, None)
            else_branch = None
            if statement.orelse:
                else_branch = IrBranch(
                    tuple(
                        self._lower_statement(child, else_names, return_type)
                        for child in statement.orelse
                    )
                )
            names.update(then_names)
            if statement.orelse:
                names.update(else_names)
            narrowed = self._none_guard_narrowing(
                statement.test,
                statement.body,
                statement.orelse,
                names,
            )
            if narrowed is not None:
                name, narrowed_type = narrowed
                names[name] = narrowed_type
            return IrIf(condition, then_branch, else_branch)
        if isinstance(statement, ast.While):
            if statement.orelse:
                self._error(
                    "XCC-AOT-LOWER-0004",
                    "Unsupported control-flow lowering: while else",
                    statement,
                )
            condition = self._lower_expr(statement.test, names, IrBoolType())
            body_names = dict(names)
            body = IrBranch(
                tuple(
                    self._lower_statement(child, body_names, return_type)
                    for child in statement.body
                )
            )
            names.update(body_names)
            return IrWhile(condition, body)
        if isinstance(statement, ast.For):
            iterable = self._lower_expr(statement.iter, names, IrTupleType(()))
            body_names = dict(names)
            self._bind_for_target(statement.target, iterable, body_names)
            body = IrBranch(
                tuple(
                    self._lower_statement(child, body_names, return_type)
                    for child in statement.body
                )
            )
            names.update(body_names)
            return IrForEach(
                ast.unparse(statement.target),
                iterable,
                body,
            )
        if isinstance(statement, ast.Raise) and isinstance(statement.exc, ast.Call):
            message: IrExpr = IrConstString("")
            if statement.exc.args:
                message = self._lower_expr(statement.exc.args[0], names, IrStringType())
            return IrRaise(ast.unparse(statement.exc.func), message)
        if isinstance(statement, ast.Assert):
            condition = self._lower_expr(statement.test, names, IrBoolType())
            return IrAssign("__assert", IrCall("__assert", (condition,), IrNoneType()))
        if isinstance(statement, ast.Pass):
            return IrAssign("__pass", IrConstNone())
        if isinstance(statement, ast.Expr):
            value = self._lower_expr(statement.value, names, return_type)
            return IrAssign("__expr", value)
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            annotated_type = self._annotation_to_ir_type(statement.annotation)
            value = (
                self._lower_expr(statement.value, names, annotated_type)
                if statement.value is not None
                else self._default_expr(annotated_type)
            )
            names[statement.target.id] = value.type
            return IrAssign(statement.target.id, value)
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Subscript)
        ):
            subscript_target = statement.targets[0]
            value_type = self._subscript_item_type(subscript_target.value, names, return_type)
            return IrSetItem(
                self._lower_expr(subscript_target.value, names, IrRecordType("object")),
                self._lower_expr(subscript_target.slice, names, IrIntType(64, signed=True)),
                self._lower_expr(statement.value, names, value_type),
            )
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], (ast.Name, ast.Attribute, ast.Tuple))
        ):
            target = statement.targets[0]
            value = self._lower_expr(
                statement.value,
                names,
                self._assignment_value_type(target, statement.value, names, return_type),
            )
            self._bind_assignment_target(target, value.type, names)
            return IrAssign(ast.unparse(target), value)
        if (
            isinstance(statement, ast.AugAssign)
            and isinstance(statement.target, (ast.Name, ast.Attribute))
            and isinstance(statement.op, (ast.Add, ast.Sub, ast.Mult))
        ):
            current = self._lower_expr(statement.target, names, return_type)
            value = self._lower_expr(statement.value, names, current.type)
            op: Literal["+", "-", "*"]
            if isinstance(statement.op, ast.Add):
                op = "+"
            elif isinstance(statement.op, ast.Sub):
                op = "-"
            else:
                op = "*"
            result = IrBinary(op, current, value, current.type)
            self._bind_assignment_target(statement.target, result.type, names)
            return IrAssign(ast.unparse(statement.target), result)
        if isinstance(statement, ast.Return):
            if statement.value is None:
                return IrReturn(IrConstNone())
            return IrReturn(self._lower_expr(statement.value, names, return_type))
        if isinstance(statement, ast.Break):
            return IrBreak()
        if isinstance(statement, ast.Continue):
            return IrContinue()
        self._error(
            "XCC-AOT-LOWER-0001",
            f"Unsupported lowered statement: {type(statement).__name__}",
            statement,
        )

    def _lower_expr(self, expr: ast.expr, names: dict[str, IrType], expected: IrType) -> IrExpr:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, bool):
                return IrConstBool(expr.value)
            if expr.value is None:
                return IrConstNone()
            if isinstance(expr.value, int) and isinstance(expected, IrIntType):
                return IrConstInt(expr.value, expected)
            if isinstance(expr.value, int) and isinstance(expected, IrRecordType):
                return IrConstInt(expr.value, IrIntType(64, signed=True))
            if isinstance(expr.value, str):
                return IrConstString(expr.value)
            if isinstance(expr.value, bytes):
                return IrConstString(expr.value.decode("utf-8"))
            if isinstance(expr.value, float):
                return IrConstFloat(expr.value)
        if isinstance(expr, ast.Name):
            value_type = names.get(expr.id)
            if value_type is None:
                if expr.id in self.global_names or expr.id in _ALLOWED_BUILTIN_VALUES:
                    return IrName(expr.id, expected)
                self._error("XCC-AOT-LOWER-0002", f"Unknown lowered name: {expr.id}", expr)
            return IrName(expr.id, value_type)
        if isinstance(expr, ast.Attribute):
            if isinstance(expr.value, ast.Name):
                class_info = self.class_types.get(expr.value.id)
                if class_info is not None and _is_enum_class(class_info):
                    return IrEnumMember(expr.value.id, expr.attr)
                if class_info is not None and expr.attr in class_info.int_constants:
                    return IrConstInt(
                        class_info.int_constants[expr.attr],
                        expected if isinstance(expected, IrIntType) else IrIntType(64, signed=True),
                    )
            value = self._lower_expr(expr.value, names, expected)
            if isinstance(value.type, IrRecordType) and value.type.name in self.class_types:
                field_type = names.get(ast.unparse(expr))
                if field_type is None:
                    field_type = self._record_field_type(value.type, expr.attr, expr)
                return IrGetField(value, expr.attr, field_type)
            self._error(
                "XCC-AOT-LOWER-0002",
                f"Unsupported field access: {expr.attr}",
                expr,
            )
        if isinstance(expr, ast.Call):
            return self._lower_call(expr, names, expected)
        if isinstance(expr, ast.JoinedStr):
            return self._lower_joined_str(expr, names)
        if isinstance(expr, ast.Compare):
            return self._lower_compare(expr, names)
        if isinstance(expr, ast.BoolOp):
            return self._lower_bool_op(expr, names)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            return IrCall(
                "__not",
                (self._lower_expr(expr.operand, names, IrBoolType()),),
                IrBoolType(),
            )
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.USub)
            and isinstance(expr.operand, ast.Constant)
            and type(expr.operand.value) is int
            and isinstance(expected, IrIntType)
        ):
            return IrConstInt(-expr.operand.value, expected)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.UAdd):
            return self._lower_expr(expr.operand, names, expected)
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.USub)
            and isinstance(expected, IrIntType)
        ):
            return IrBinary(
                "-",
                IrConstInt(0, expected),
                self._lower_expr(expr.operand, names, expected),
                expected,
            )
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.Invert)
            and isinstance(expected, IrIntType)
        ):
            return IrBinary(
                "-",
                IrConstInt(-1, expected),
                self._lower_expr(expr.operand, names, expected),
                expected,
            )
        if isinstance(expr, ast.IfExp):
            body_names = dict(names)
            narrowed = self._isinstance_guard_narrowing(expr.test, names)
            if narrowed is not None:
                name, narrowed_type = narrowed
                body_names[name] = narrowed_type
            return IrCall(
                "__ifexp",
                (
                    self._lower_expr(expr.test, names, IrBoolType()),
                    self._lower_expr(expr.body, body_names, expected),
                    self._lower_expr(expr.orelse, names, expected),
                ),
                expected,
            )
        if isinstance(expr, ast.Tuple):
            elements = tuple(self._lower_expr(element, names, expected) for element in expr.elts)
            return IrTuple(elements, IrTupleType(tuple(element.type for element in elements)))
        if isinstance(expr, (ast.List, ast.Set)):
            elements = tuple(self._lower_expr(element, names, expected) for element in expr.elts)
            return IrTuple(elements, IrTupleType(tuple(element.type for element in elements)))
        if isinstance(expr, ast.Dict) and not expr.keys and not expr.values:
            return IrTuple((), expected if isinstance(expected, IrTupleType) else IrTupleType(()))
        if isinstance(expr, (ast.ListComp, ast.GeneratorExp)):
            return IrCall(f"__{type(expr).__name__}", (), IrTupleType(()))
        if isinstance(expr, ast.Subscript):
            value = self._lower_expr(expr.value, names, expected)
            if isinstance(expr.slice, ast.Slice):
                return IrTupleSlice(
                    value,
                    _constant_int_or_none(expr.slice.lower),
                    _constant_int_or_none(expr.slice.upper),
                )
            return IrCall(
                "__getitem",
                (value, self._lower_expr(expr.slice, names, IrIntType(64, signed=True))),
                expected,
            )
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Sub, ast.Mult)):
            if isinstance(expr.op, ast.Add) and isinstance(expected, IrStringType):
                return IrStringConcat(
                    (
                        self._lower_expr(expr.left, names, expected),
                        self._lower_expr(expr.right, names, expected),
                    )
                )
            if isinstance(expr.op, ast.Add) and not isinstance(expected, IrIntType):
                return IrCall(
                    "__add",
                    (
                        self._lower_expr(expr.left, names, expected),
                        self._lower_expr(expr.right, names, expected),
                    ),
                    expected,
                )
            op: Literal["+", "-", "*"]
            if isinstance(expr.op, ast.Add):
                op = "+"
            elif isinstance(expr.op, ast.Sub):
                op = "-"
            else:
                op = "*"
            return IrBinary(
                op,
                self._lower_expr(expr.left, names, expected),
                self._lower_expr(expr.right, names, expected),
                expected,
            )
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered expression: {type(expr).__name__}",
            expr,
        )

    def _annotation_to_ir_type(self, annotation: ast.expr | None) -> IrType:
        if annotation is None:
            self._error("XCC-AOT-LOWER-0001", "Missing lowered annotation", ast.Pass())
        name = annotation_name(annotation)
        if (
            isinstance(annotation, ast.Constant)
            and isinstance(annotation.value, str)
            and (name in {"bool", "int", "None", "str"} or _width_alias_to_ir_type(name))
        ):
            self._error(
                "XCC-AOT-LOWER-0002",
                f"Unsupported lowered annotation: {name}",
                annotation,
            )
        return self._type_name_to_ir_type(name, annotation)

    def _type_name_to_ir_type(self, name: str, node: ast.AST) -> IrType:
        alias = self.aliases.get(name)
        if alias is not None:
            return self._aot_type_to_ir_type(alias)
        if name == "str":
            return IrStringType()
        if name == "int":
            return IrIntType(64, signed=True)
        if name == "bool":
            return IrBoolType()
        if name == "None":
            return IrNoneType()
        if name == "NoReturn":
            return IrNoneType()
        if name == "Enum":
            return IrRecordType("Enum")
        if name in self.class_types:
            return IrRecordType(name)
        width_type = _width_alias_to_ir_type(name)
        if width_type is not None:
            return width_type
        if name.startswith("Literal["):
            return IrStringType()
        if _is_tuple_backed_container_type(name):
            return IrTupleType(self._tuple_backed_container_types(name, node))
        if _is_optional_int(name):
            return IrIntType(64, signed=True)
        if " | " in name:
            return IrRecordType(name)
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered annotation: {name}",
            node,
        )

    def _lower_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if isinstance(expr.func, ast.Name) and expr.func.id == "llvm":
            return self._lower_llvm_api_constructor(expr)
        if isinstance(expr.func, ast.Name) and expr.func.id == "enumerate":
            return self._lower_enumerate_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "len" and len(expr.args) == 1:
            return IrCall(
                "len",
                (self._lower_expr(expr.args[0], names, IrTupleType(())),),
                IrIntType(64, signed=True),
            )
        if isinstance(expr.func, ast.Name) and expr.func.id == "int":
            return self._lower_int_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id in self.class_types:
            record_name = expr.func.id
            record_type = IrRecordType(record_name)
            args = self._lower_constructor_args(record_name, expr, names)
            return IrConstructRecord(record_name, args, record_type)
        if isinstance(expr.func, ast.Name):
            if expr.func.id not in self.global_names and expr.func.id not in _ALLOWED_BUILTIN_CALLS:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    f"Unsupported call target: {ast.unparse(expr.func)}",
                    expr,
                )
            return_type = self._function_return_type(expr.func.id, expected)
            return IrCall(
                expr.func.id,
                self._lower_call_args_for_signature(expr, names, expr.func.id, 0, expected),
                return_type,
            )
        if isinstance(expr.func, ast.Attribute) and _is_string_join_call(expr.func):
            receiver = self._lower_expr(expr.func.value, names, IrStringType())
            values = (
                self._lower_expr(expr.args[0], names, IrTupleType(()))
                if expr.args
                else IrTuple((), IrTupleType(()))
            )
            return IrStringJoin(receiver, values)
        if _is_object_setattr_call(expr):
            value = (
                self._lower_expr(expr.args[2], names, expected)
                if len(expr.args) >= 3
                else IrConstNone()
            )
            return IrCall("object.__setattr__", (value,), value.type)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "startswith":
            receiver = self._lower_expr(expr.func.value, names, IrStringType())
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_startswith_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "encode":
            receiver = self._lower_expr(expr.func.value, names, IrStringType())
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_encode_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in _STRING_PREDICATE_METHODS:
            receiver = self._lower_expr(expr.func.value, names, IrStringType())
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_predicate_call(expr, expr.func.attr, receiver)
        if isinstance(expr.func, ast.Attribute):
            receiver = self._lower_expr(expr.func.value, names, expected)
            receiver_type = receiver.type
            if isinstance(receiver_type, IrRecordType) and receiver_type.name == _LLVM_API_RECORD:
                return self._lower_llvm_api_call(expr, names, expected)
            if isinstance(receiver_type, IrRecordType):
                target = f"{receiver_type.name}.{expr.func.attr}"
                return_type = self._function_return_type(target, expected)
                args = (receiver,) + tuple(
                    self._lower_call_args_for_signature(expr, names, target, 1, expected)
                )
                return IrCall(target, args, return_type)
            if isinstance(receiver_type, IrTupleType) and expr.func.attr == "get":
                return self._lower_dict_get_call(expr, receiver, names)
            if (
                isinstance(receiver_type, IrTupleType)
                and expr.func.attr in _ALLOWED_MUTATING_TUPLE_CALLS
            ):
                return IrCall(
                    ast.unparse(expr.func),
                    (receiver,) + self._lower_call_args(expr, names, expected),
                    expected,
                )
            if expr.func.attr == "__init__" and _is_super_call(expr.func.value):
                return IrCall(
                    ast.unparse(expr.func),
                    (receiver,) + self._lower_call_args(expr, names, expected),
                    expected,
                )
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        self._error(
            "XCC-AOT-LOWER-0003",
            f"Unsupported call target: {ast.unparse(expr.func)}",
            expr,
        )

    def _lower_int_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
    ) -> IrExpr:
        int64 = IrIntType(64, signed=True)
        if not expr.keywords and len(expr.args) == 1:
            return IrCall(
                "__ifexp",
                (
                    self._lower_expr(expr.args[0], names, IrBoolType()),
                    IrConstInt(1, int64),
                    IrConstInt(0, int64),
                ),
                int64,
            )
        if expr.keywords or len(expr.args) != 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__int_parse",
            (
                self._lower_expr(expr.args[0], names, IrStringType()),
                self._lower_expr(expr.args[1], names, int64),
            ),
            int64,
        )

    def _lower_string_startswith_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) not in {1, 2}:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        start = (
            self._lower_expr(expr.args[1], names, int64)
            if len(expr.args) == 2
            else IrConstInt(0, int64)
        )
        return IrCall(
            "__str_startswith",
            (
                receiver,
                self._lower_expr(expr.args[0], names, IrStringType()),
                start,
            ),
            IrBoolType(),
        )

    def _lower_string_encode_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) > 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if expr.args:
            self._lower_expr(expr.args[0], names, IrStringType())
        return receiver

    def _lower_string_predicate_call(
        self,
        expr: ast.Call,
        method: str,
        receiver: IrExpr,
    ) -> IrExpr:
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(f"__str_{method}", (receiver,), IrBoolType())

    def _lower_call_args(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> tuple[IrExpr, ...]:
        args = [self._lower_expr(arg, names, expected) for arg in expr.args]
        for keyword in expr.keywords:
            if keyword.arg is None:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    "Unsupported call target: **kwargs",
                    keyword,
                )
            args.append(self._lower_expr(keyword.value, names, expected))
        return tuple(args)

    def _lower_call_args_for_signature(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        target: str,
        skip_parameters: int,
        fallback: IrType,
    ) -> tuple[IrExpr, ...]:
        function_info = self.function_types.get(target)
        if function_info is None:
            return self._lower_call_args(expr, names, fallback)
        parameters = function_info.parameters[skip_parameters:]
        args: list[IrExpr] = []
        for index, arg in enumerate(expr.args):
            arg_type = (
                self._type_name_to_ir_type(parameters[index][1], arg)
                if index < len(parameters)
                else fallback
            )
            args.append(self._lower_expr(arg, names, arg_type))
        parameter_types = {
            parameter_name: self._type_name_to_ir_type(parameter_type, expr)
            for parameter_name, parameter_type in parameters
        }
        for keyword in expr.keywords:
            if keyword.arg is None:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    "Unsupported call target: **kwargs",
                    keyword,
                )
            args.append(
                self._lower_expr(
                    keyword.value,
                    names,
                    parameter_types.get(keyword.arg, fallback),
                )
            )
        return tuple(args)

    def _function_return_type(
        self,
        target: str,
        fallback: IrType,
    ) -> IrType:
        function_info = self.function_types.get(target)
        if function_info is None:
            return fallback
        return self._aot_type_to_ir_type(function_info.return_type)

    def _lower_constructor_args(
        self,
        record_name: str,
        expr: ast.Call,
        names: dict[str, IrType],
    ) -> tuple[IrExpr, ...]:
        class_info = self.class_types[record_name]
        field_items = tuple(class_info.fields.items())
        keyword_values = {
            keyword.arg: keyword.value for keyword in expr.keywords if keyword.arg is not None
        }
        args: list[IrExpr] = []
        for index, (field_name, field_type) in enumerate(field_items):
            ir_type = self._aot_type_to_ir_type(field_type)
            if index < len(expr.args):
                args.append(self._lower_expr(expr.args[index], names, ir_type))
            elif field_name in keyword_values:
                args.append(self._lower_expr(keyword_values[field_name], names, ir_type))
            else:
                args.append(self._default_expr(ir_type))
        return tuple(args)

    def _record_field_types(self, record_name: str) -> tuple[IrType, ...]:
        class_info = self.class_types[record_name]
        return tuple(self._aot_type_to_ir_type(field) for field in class_info.fields.values())

    def _record_field_type(self, record_type: IrType, field: str, node: ast.AST) -> IrType:
        if isinstance(record_type, IrRecordType):
            class_info = self.class_types[record_type.name]
            field_type = class_info.fields.get(field)
            if field_type is not None:
                return self._aot_type_to_ir_type(field_type)
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported field access: {field}",
            node,
        )

    def _aot_type_to_ir_type(self, type_info: AotType) -> IrType:
        if type_info.bits is not None and type_info.signed is not None:
            return IrIntType(type_info.bits, type_info.signed)
        if type_info.name == "str":
            return IrStringType()
        if type_info.name == "float":
            return IrFloatType()
        if type_info.name == "int":
            return IrIntType(64, signed=True)
        if type_info.name == "bool":
            return IrBoolType()
        if type_info.name == "None":
            return IrNoneType()
        if type_info.name == "NoReturn":
            return IrNoneType()
        if type_info.name == "Enum":
            return IrRecordType("Enum")
        if type_info.name in self.class_types:
            return IrRecordType(type_info.name)
        if type_info.name.startswith("Literal["):
            return IrStringType()
        if _is_tuple_backed_container_type(type_info.name):
            return IrTupleType(self._tuple_backed_container_types(type_info.name, ast.Pass()))
        if _is_optional_int(type_info.name):
            return IrIntType(64, signed=True)
        if " | " in type_info.name:
            return IrRecordType(type_info.name)
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered type: {type_info.name}",
            ast.Pass(),
        )

    def _bind_assignment_target(
        self,
        target: ast.expr,
        value_type: IrType,
        names: dict[str, IrType],
    ) -> None:
        if isinstance(target, ast.Name):
            names[target.id] = value_type
            return
        if isinstance(target, ast.Tuple):
            for element in target.elts:
                self._bind_assignment_target(element, IrRecordType("object"), names)
            return
        if isinstance(target, ast.Attribute):
            names[ast.unparse(target)] = value_type
            return
        self._error(
            "XCC-AOT-LOWER-0001",
            f"Unsupported assignment target: {type(target).__name__}",
            target,
        )

    def _bind_for_target(
        self,
        target: ast.expr,
        iterable: IrExpr,
        names: dict[str, IrType],
    ) -> None:
        if isinstance(iterable, IrCall) and iterable.target == "__enumerate":
            if not isinstance(target, ast.Tuple):
                self._error(
                    "XCC-AOT-LOWER-0001",
                    "Unsupported enumerate target",
                    target,
                )
            if not isinstance(iterable.type, IrTupleType) or len(iterable.type.elements) != len(
                target.elts
            ):
                self._error(
                    "XCC-AOT-LOWER-0001",
                    "Unsupported enumerate target shape",
                    target,
                )
            for element, element_type in zip(target.elts, iterable.type.elements, strict=True):
                if isinstance(element, ast.Name) and element.id == "_":
                    continue
                if not isinstance(element, ast.Name):
                    self._error(
                        "XCC-AOT-LOWER-0001",
                        "Unsupported enumerate target",
                        element,
                    )
                names[element.id] = element_type
            return
        self._bind_assignment_target(target, _for_each_target_type(iterable.type), names)

    def _assignment_value_type(
        self,
        target: ast.expr,
        value: ast.expr,
        names: dict[str, IrType],
        fallback: IrType,
    ) -> IrType:
        if isinstance(target, ast.Name):
            return names.get(target.id) or self._infer_assignment_expr_type(value, names, fallback)
        if isinstance(target, ast.Attribute):
            receiver = self._lower_expr(target.value, names, IrRecordType("object"))
            if isinstance(receiver.type, IrRecordType) and receiver.type.name in self.class_types:
                return self._record_field_type(receiver.type, target.attr, target)
        return fallback

    def _subscript_item_type(
        self,
        target: ast.expr,
        names: dict[str, IrType],
        fallback: IrType,
    ) -> IrType:
        target_expr = self._lower_expr(target, names, IrRecordType("object"))
        if isinstance(target_expr.type, IrTupleType) and len(target_expr.type.elements) == 1:
            return target_expr.type.elements[0]
        return fallback

    def _infer_assignment_expr_type(
        self,
        expr: ast.expr,
        names: dict[str, IrType],
        fallback: IrType,
    ) -> IrType:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, bool):
                return IrBoolType()
            if expr.value is None:
                return IrNoneType()
            if isinstance(expr.value, int):
                return IrIntType(64, signed=True)
            if isinstance(expr.value, str):
                return IrStringType()
        if isinstance(expr, ast.IfExp):
            body_type = self._infer_assignment_expr_type(expr.body, names, fallback)
            orelse_type = self._infer_assignment_expr_type(expr.orelse, names, fallback)
            if body_type == orelse_type:
                return body_type
        if isinstance(expr, ast.Name):
            return names.get(expr.id, fallback)
        return fallback

    def _default_expr(self, type_info: IrType) -> IrExpr:
        if isinstance(type_info, IrIntType):
            return IrConstInt(0, type_info)
        if isinstance(type_info, IrBoolType):
            return IrConstBool(False)
        if isinstance(type_info, IrStringType):
            return IrConstString("")
        if isinstance(type_info, IrNoneType):
            return IrConstNone()
        if isinstance(type_info, IrTupleType):
            return IrTuple((), type_info)
        return IrConstNone()

    def _tuple_backed_container_element_type(
        self,
        name: str,
        node: ast.AST,
    ) -> IrType | None:
        element_name = _tuple_backed_container_element_name(name)
        if element_name is None:
            return None
        return self._optional_container_type(element_name, node)

    def _tuple_backed_container_types(
        self,
        name: str,
        node: ast.AST,
    ) -> tuple[IrType, ...]:
        dict_names = _dict_container_type_names(name)
        if dict_names is not None:
            key_type = self._optional_container_type(dict_names[0], node)
            value_type = self._optional_container_type(dict_names[1], node)
            if key_type is not None and value_type is not None:
                return (key_type, value_type)
            return ()
        element_type = self._tuple_backed_container_element_type(name, node)
        if element_type is not None:
            return (element_type,)
        return ()

    def _optional_container_type(self, name: str, node: ast.AST) -> IrType | None:
        try:
            return self._type_name_to_ir_type(name, node)
        except AotError:
            return None

    def _lower_llvm_api_constructor(self, expr: ast.Call) -> IrExpr:
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall("__llvm_api", (), IrRecordType(_LLVM_API_RECORD))

    def _lower_llvm_api_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if not isinstance(expr.func, ast.Attribute):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        method = expr.func.attr
        return IrCall(
            f"__llvm_{method}",
            self._lower_call_args(expr, names, IrRecordType("object")),
            _llvm_api_call_return_type(method, expected),
        )

    def _lower_enumerate_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        iterable = self._lower_expr(expr.args[0], names, IrTupleType(()))
        return IrCall(
            "__enumerate",
            (iterable,),
            IrTupleType((IrIntType(64, signed=True), _for_each_target_type(iterable.type))),
        )

    def _lower_dict_get_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 1 or not isinstance(receiver.type, IrTupleType):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if len(receiver.type.elements) != 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        key_type, value_type = receiver.type.elements
        return IrCall(
            "__dict_get",
            (receiver, self._lower_expr(expr.args[0], names, key_type)),
            _dict_get_result_type(value_type),
        )

    def _none_guard_narrowing(
        self,
        test: ast.expr,
        body: list[ast.stmt],
        orelse: list[ast.stmt],
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        if orelse or not _statements_exit(body):
            return None
        name = _none_guard_name(test)
        if name is None:
            return None
        narrowed = self._optional_record_inner(names.get(name))
        if narrowed is None:
            return None
        return name, narrowed

    def _optional_record_inner(self, type_info: IrType | None) -> IrRecordType | None:
        if not isinstance(type_info, IrRecordType):
            return None
        parts = tuple(part.strip() for part in type_info.name.split("|"))
        non_none = tuple(part for part in parts if part != "None")
        if len(non_none) == 1 and len(non_none) != len(parts) and non_none[0] in self.class_types:
            return IrRecordType(non_none[0])
        return None

    def _isinstance_guard_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrRecordType] | None:
        if (
            not isinstance(test, ast.Call)
            or not isinstance(test.func, ast.Name)
            or test.func.id != "isinstance"
            or test.keywords
            or len(test.args) != 2
        ):
            return None
        value, target_type = test.args
        if not isinstance(value, ast.Name) or not isinstance(target_type, ast.Name):
            return None
        if target_type.id not in self.class_types:
            return None
        current = names.get(value.id)
        if not _can_narrow_to_record(current, target_type.id, self.class_types):
            return None
        return value.id, IrRecordType(target_type.id)

    def _truthy_optional_record_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrRecordType] | None:
        if not isinstance(test, ast.Name | ast.Attribute):
            return None
        try:
            value = self._lower_expr(test, names, IrRecordType("object"))
        except AotError:
            return None
        narrowed = self._optional_record_inner(value.type)
        if narrowed is None:
            return None
        return ast.unparse(test), narrowed

    def _not_none_guard_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrRecordType] | None:
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], ast.IsNot)
            or len(test.comparators) != 1
        ):
            return None
        guarded: ast.expr | None = None
        if _is_none_constant(test.left):
            guarded = test.comparators[0]
        elif _is_none_constant(test.comparators[0]):
            guarded = test.left
        if guarded is None or not isinstance(guarded, ast.Name | ast.Attribute):
            return None
        try:
            value = self._lower_expr(guarded, names, IrRecordType("object"))
        except AotError:
            return None
        narrowed = self._optional_record_inner(value.type)
        if narrowed is None:
            return None
        return ast.unparse(guarded), narrowed

    def _lower_compare(self, expr: ast.Compare, names: dict[str, IrType]) -> IrExpr:
        if len(expr.ops) != len(expr.comparators) or not expr.ops:
            self._error(
                "XCC-AOT-LOWER-0004",
                "Unsupported control-flow lowering: malformed compare",
                expr,
            )
        comparisons: list[IrExpr] = []
        left = expr.left
        for op, right in zip(expr.ops, expr.comparators, strict=True):
            comparisons.append(
                IrCall(
                    f"__cmp_{type(op).__name__}",
                    (
                        self._lower_expr(left, names, IrRecordType("object")),
                        self._lower_expr(right, names, IrRecordType("object")),
                    ),
                    IrBoolType(),
                )
            )
            left = right
        if len(comparisons) == 1:
            return comparisons[0]
        return IrCall("__bool_and", tuple(comparisons), IrBoolType())

    def _lower_bool_op(self, expr: ast.BoolOp, names: dict[str, IrType]) -> IrExpr:
        target = "__bool_and" if isinstance(expr.op, ast.And) else "__bool_or"
        return IrCall(
            target,
            tuple(self._lower_expr(value, names, IrBoolType()) for value in expr.values),
            IrBoolType(),
        )

    def _lower_joined_str(self, expr: ast.JoinedStr, names: dict[str, IrType]) -> IrExpr:
        parts: list[IrExpr] = []
        for value in expr.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(IrConstString(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append(self._lower_expr(value.value, names, IrStringType()))
            else:
                self._error(
                    "XCC-AOT-LOWER-0005",
                    "Unsupported runtime operation lowering: f-string part",
                    value,
                )
        return IrStringConcat(tuple(parts))

    def _error(self, code: str, message: str, node: ast.AST) -> NoReturn:
        line, column = node_location(node)
        raise AotError(
            (
                AotDiagnostic(
                    code,
                    message,
                    filename=self.filename,
                    line=line,
                    column=column,
                ),
            )
        )


def _width_alias_to_ir_type(name: str) -> IrIntType | None:
    if name.startswith("uint") and name[4:].isdigit():
        return IrIntType(int(name[4:]), signed=False)
    if name.startswith("int") and name[3:].isdigit():
        return IrIntType(int(name[3:]), signed=True)
    if name == "usize":
        return IrIntType(64, signed=False)
    return None


def _lowered_function_name(name: str, owner: str | None) -> str:
    return f"{owner}.{name}" if owner is not None else name


def _is_optional_int(name: str) -> bool:
    return name in {"int | None", "None | int"}


def _is_tuple_backed_container_type(name: str) -> bool:
    return name.startswith(
        (
            "Iterable[",
            "Sequence[",
            "dict[",
            "frozenset[",
            "list[",
            "set[",
            "tuple[",
        )
    )


def _tuple_backed_container_element_name(name: str) -> str | None:
    if name.startswith(("dict[", "Dict[")):
        return None
    if not name.startswith(
        (
            "Iterable[",
            "Sequence[",
            "frozenset[",
            "list[",
            "set[",
            "tuple[",
        )
    ):
        return None
    if not name.endswith("]"):
        return None
    content = name[name.find("[") + 1 : -1]
    first = _first_annotation_arg(content)
    if first == "..." or not first:
        return None
    return _strip_annotation_quotes(first)


def _dict_container_type_names(name: str) -> tuple[str, str] | None:
    if not name.startswith(("dict[", "Dict[")) or not name.endswith("]"):
        return None
    content = name[name.find("[") + 1 : -1]
    args = _annotation_args(content)
    if len(args) != 2:
        return None
    return (_strip_annotation_quotes(args[0]), _strip_annotation_quotes(args[1]))


def _annotation_args(content: str) -> tuple[str, ...]:
    args: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(content):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(content[start:index].strip())
            start = index + 1
    args.append(content[start:].strip())
    return tuple(arg for arg in args if arg)


def _first_annotation_arg(content: str) -> str:
    depth = 0
    for index, char in enumerate(content):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            return content[:index].strip()
    return content.strip()


def _strip_annotation_quotes(name: str) -> str:
    if len(name) >= 2 and name[0] == name[-1] and name[0] in {"'", '"'}:
        return name[1:-1]
    return name


def _for_each_target_type(iterable_type: IrType) -> IrType:
    if isinstance(iterable_type, IrTupleType) and len(iterable_type.elements) == 1:
        return iterable_type.elements[0]
    return IrRecordType("object")


def _llvm_api_call_return_type(method: str, expected: IrType) -> IrType:
    if method in {"PositionBuilderAtEnd", "SetInitializer", "SetLinkage", "SetTarget"}:
        return IrNoneType()
    if not isinstance(expected, IrNoneType):
        return expected
    return IrIntType(64, signed=True)


def _dict_get_result_type(value_type: IrType) -> IrType:
    if isinstance(value_type, IrRecordType):
        if "None" in (part.strip() for part in value_type.name.split("|")):
            return value_type
        return IrRecordType(f"{value_type.name} | None")
    return value_type


def _can_narrow_to_record(
    type_info: IrType | None,
    record_name: str,
    class_types: dict[str, AotClassInfo],
) -> bool:
    if not isinstance(type_info, IrRecordType):
        return False
    if type_info.name == "object":
        return True
    return any(
        _record_extends(record_name, part.strip(), class_types)
        for part in type_info.name.split("|")
    )


def _record_extends(
    record_name: str,
    base_name: str,
    class_types: dict[str, AotClassInfo],
) -> bool:
    if record_name == base_name:
        return True
    class_info = class_types.get(record_name)
    if class_info is None:
        return False
    return any(
        base == base_name or _record_extends(base, base_name, class_types)
        for base in class_info.bases
    )


def _none_guard_name(test: ast.expr) -> str | None:
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and len(test.comparators) == 1
    ):
        if isinstance(test.left, ast.Name) and _is_none_constant(test.comparators[0]):
            return test.left.id
        if _is_none_constant(test.left) and isinstance(test.comparators[0], ast.Name):
            return test.comparators[0].id
    return None


def _is_none_constant(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is None


def _statements_exit(statements: list[ast.stmt]) -> bool:
    return bool(statements) and isinstance(statements[-1], (ast.Return, ast.Raise))


def _collect_global_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
        elif isinstance(statement, (ast.ClassDef, ast.FunctionDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
    return names


def _constant_int_or_none(expr: ast.expr | None) -> int | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return expr.value
    return None


def _is_string_join_call(expr: ast.Attribute) -> bool:
    return expr.attr == "join"


def _is_object_setattr_call(expr: ast.Call) -> bool:
    return (
        isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "__setattr__"
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == "object"
    )


def _is_super_call(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "super"
        and not expr.args
        and not expr.keywords
    )


def _is_enum_class(class_info: AotClassInfo) -> bool:
    return any(base == "Enum" or base.endswith(".Enum") for base in class_info.bases)
