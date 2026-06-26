import ast
from typing import Literal, NoReturn

from xcc.aot.analysis import analyze_source
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrCall,
    IrConstInt,
    IrConstructRecord,
    IrConstString,
    IrExpr,
    IrField,
    IrFunction,
    IrGetField,
    IrIntType,
    IrModule,
    IrName,
    IrParam,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrStmt,
    IrStringType,
    IrType,
)
from xcc.aot.types import AotClassInfo, AotType


def lower_source_to_ir(
    source: str,
    *,
    filename: str = "<input>",
    entry: str | None = None,
) -> IrModule:
    analysis = analyze_source(source, filename=filename)
    lowerer = _Lowerer(filename, analysis.types.classes)
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
    def __init__(self, filename: str, class_types: dict[str, AotClassInfo]) -> None:
        self.filename = filename
        self.class_types = class_types

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
        return tuple(params), names

    def _lower_statement(
        self,
        statement: ast.stmt,
        names: dict[str, IrType],
        return_type: IrType,
    ) -> IrStmt:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            value = self._lower_expr(statement.value, names, return_type)
            names[statement.targets[0].id] = value.type
            return IrAssign(statement.targets[0].id, value)
        if isinstance(statement, ast.Return) and statement.value is not None:
            return IrReturn(self._lower_expr(statement.value, names, return_type))
        self._error(
            "XCC-AOT-LOWER-0001",
            f"Unsupported lowered statement: {type(statement).__name__}",
            statement,
        )

    def _lower_expr(self, expr: ast.expr, names: dict[str, IrType], expected: IrType) -> IrExpr:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, int) and isinstance(expected, IrIntType):
                return IrConstInt(expr.value, expected)
            if isinstance(expr.value, str):
                return IrConstString(expr.value)
        if isinstance(expr, ast.Name):
            value_type = names.get(expr.id)
            if value_type is None:
                self._error("XCC-AOT-LOWER-0002", f"Unknown lowered name: {expr.id}", expr)
            return IrName(expr.id, value_type)
        if isinstance(expr, ast.Attribute):
            value = self._lower_expr(expr.value, names, expected)
            field_type = self._record_field_type(value.type, expr.attr, expr)
            return IrGetField(value, expr.attr, field_type)
        if isinstance(expr, ast.Call):
            return self._lower_call(expr, names, expected)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Sub, ast.Mult)):
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
        if isinstance(annotation, ast.Name):
            name = annotation.id
            if name == "str":
                return IrStringType()
            if name == "int":
                return IrIntType(64, signed=True)
            if name in self.class_types:
                return IrRecordType(name)
            width_type = _width_alias_to_ir_type(name)
            if width_type is not None:
                return width_type
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered annotation: {ast.unparse(annotation)}",
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
            args = tuple(
                self._lower_expr(arg, names, field_type)
                for arg, field_type in zip(
                    expr.args,
                    self._record_field_types(record_name),
                    strict=True,
                )
            )
            return IrConstructRecord(record_name, args, record_type)
        if isinstance(expr.func, ast.Attribute):
            receiver = self._lower_expr(expr.func.value, names, expected)
            receiver_type = receiver.type
            if isinstance(receiver_type, IrRecordType):
                target = f"{receiver_type.name}.{expr.func.attr}"
                args = (receiver,) + tuple(
                    self._lower_expr(arg, names, expected) for arg in expr.args
                )
                return IrCall(target, args, expected)
        self._error(
            "XCC-AOT-LOWER-0003",
            f"Unsupported call target: {ast.unparse(expr.func)}",
            expr,
        )

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
        if type_info.name in self.class_types:
            return IrRecordType(type_info.name)
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered type: {type_info.name}",
            ast.Pass(),
        )

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
