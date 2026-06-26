import ast
from typing import Literal, NoReturn

from xcc.aot.analysis import analyze_source
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBranch,
    IrCall,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrExpr,
    IrField,
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
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrType,
)
from xcc.aot.types import AotClassInfo, AotType, annotation_name

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
_ALLOWED_MUTATING_TUPLE_CALLS = {"append", "extend"}


def lower_source_to_ir(
    source: str,
    *,
    filename: str = "<input>",
    entry: str | None = None,
) -> IrModule:
    analysis = analyze_source(source, filename=filename)
    lowerer = _Lowerer(
        filename,
        analysis.types.classes,
        analysis.types.aliases,
        _collect_global_names(analysis.module.tree),
    )
    records = tuple(
        lowerer.lower_record(node)
        for node in analysis.module.tree.body
        if isinstance(node, ast.ClassDef)
    )
    functions: list[IrFunction] = []
    for node in analysis.module.tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    functions.append(lowerer.lower_function(child, owner=node.name))
    for node in analysis.module.tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append(lowerer.lower_function(node, owner=None))
    return IrModule(filename, records, tuple(functions), entry=entry)


class _Lowerer:
    def __init__(
        self,
        filename: str,
        class_types: dict[str, AotClassInfo],
        aliases: dict[str, AotType] | None = None,
        global_names: set[str] | None = None,
    ) -> None:
        self.filename = filename
        self.class_types = class_types
        self.aliases = aliases or {}
        self.global_names = global_names or set()

    def lower_record(self, node: ast.ClassDef) -> IrRecord:
        class_info = self.class_types[node.name]
        fields = tuple(
            IrField(name, self._aot_type_to_ir_type(field_type))
            for name, field_type in class_info.fields.items()
        )
        return IrRecord(node.name, fields)

    def lower_function(self, node: ast.FunctionDef, *, owner: str | None) -> IrFunction:
        function_name = f"{owner}.{node.name}" if owner is not None else node.name
        params, names = self._lower_params(node, owner)
        return_type = self._annotation_to_ir_type(node.returns)
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
            then_branch = IrBranch(
                tuple(
                    self._lower_statement(child, then_names, return_type)
                    for child in statement.body
                )
            )
            else_branch = None
            if statement.orelse:
                else_branch = IrBranch(
                    tuple(
                        self._lower_statement(child, else_names, return_type)
                        for child in statement.orelse
                    )
                )
            names.update(then_names)
            names.update(else_names)
            return IrIf(condition, then_branch, else_branch)
        if isinstance(statement, ast.For):
            body_names = dict(names)
            self._bind_assignment_target(statement.target, IrRecordType("object"), body_names)
            body = IrBranch(
                tuple(
                    self._lower_statement(child, body_names, return_type)
                    for child in statement.body
                )
            )
            names.update(body_names)
            return IrForEach(
                ast.unparse(statement.target),
                self._lower_expr(statement.iter, names, IrTupleType(())),
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
            and isinstance(statement.targets[0], (ast.Name, ast.Attribute, ast.Tuple))
        ):
            value = self._lower_expr(statement.value, names, return_type)
            target = statement.targets[0]
            self._bind_assignment_target(target, value.type, names)
            return IrAssign(ast.unparse(target), value)
        if isinstance(statement, ast.Return):
            if statement.value is None:
                return IrReturn(IrConstNone())
            return IrReturn(self._lower_expr(statement.value, names, return_type))
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
        if isinstance(expr, ast.Name):
            value_type = names.get(expr.id)
            if value_type is None:
                if expr.id in self.global_names or expr.id in _ALLOWED_BUILTIN_VALUES:
                    return IrName(expr.id, expected)
                self._error("XCC-AOT-LOWER-0002", f"Unknown lowered name: {expr.id}", expr)
            return IrName(expr.id, value_type)
        if isinstance(expr, ast.Attribute):
            value = self._lower_expr(expr.value, names, expected)
            if isinstance(value.type, IrRecordType) and value.type.name in self.class_types:
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
        if isinstance(expr, ast.IfExp):
            return IrCall(
                "__ifexp",
                (
                    self._lower_expr(expr.test, names, IrBoolType()),
                    self._lower_expr(expr.body, names, expected),
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
        if name in self.class_types:
            return IrRecordType(name)
        width_type = _width_alias_to_ir_type(name)
        if width_type is not None:
            return width_type
        if name.startswith("Literal["):
            return IrStringType()
        if name.startswith(("list[", "tuple[")):
            return IrTupleType(())
        if _is_optional_int(name):
            return IrIntType(64, signed=True)
        if " | " in name:
            return IrRecordType(name)
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered annotation: {name}",
            annotation,
        )

    def _lower_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
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
            return IrCall(
                expr.func.id,
                tuple(self._lower_expr(arg, names, expected) for arg in expr.args),
                expected,
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
        if isinstance(expr.func, ast.Attribute):
            receiver = self._lower_expr(expr.func.value, names, expected)
            receiver_type = receiver.type
            if isinstance(receiver_type, IrRecordType):
                target = f"{receiver_type.name}.{expr.func.attr}"
                args = (receiver,) + tuple(
                    self._lower_expr(arg, names, expected) for arg in expr.args
                )
                return IrCall(target, args, expected)
            if (
                isinstance(receiver_type, IrTupleType)
                and expr.func.attr in _ALLOWED_MUTATING_TUPLE_CALLS
            ):
                return IrCall(
                    ast.unparse(expr.func),
                    (receiver,)
                    + tuple(self._lower_expr(arg, names, expected) for arg in expr.args),
                    expected,
                )
            if expr.func.attr == "__init__" and _is_super_call(expr.func.value):
                return IrCall(
                    ast.unparse(expr.func),
                    (receiver,)
                    + tuple(self._lower_expr(arg, names, expected) for arg in expr.args),
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
        if type_info.name == "int":
            return IrIntType(64, signed=True)
        if type_info.name == "bool":
            return IrBoolType()
        if type_info.name == "None":
            return IrNoneType()
        if type_info.name in self.class_types:
            return IrRecordType(type_info.name)
        if type_info.name.startswith("Literal["):
            return IrStringType()
        if type_info.name.startswith(("list[", "tuple[")):
            return IrTupleType(())
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

    def _lower_compare(self, expr: ast.Compare, names: dict[str, IrType]) -> IrExpr:
        if len(expr.ops) != 1 or len(expr.comparators) != 1:
            self._error(
                "XCC-AOT-LOWER-0004",
                "Unsupported control-flow lowering: chained compare",
                expr,
            )
        return IrCall(
            f"__cmp_{type(expr.ops[0]).__name__}",
            (
                self._lower_expr(expr.left, names, IrRecordType("object")),
                self._lower_expr(expr.comparators[0], names, IrRecordType("object")),
            ),
            IrBoolType(),
        )

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
        raise AotError(
            (
                AotDiagnostic(
                    code,
                    message,
                    filename=self.filename,
                    line=getattr(node, "lineno", None),
                    column=getattr(node, "col_offset", None),
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


def _is_optional_int(name: str) -> bool:
    return name in {"int | None", "None | int"}


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
