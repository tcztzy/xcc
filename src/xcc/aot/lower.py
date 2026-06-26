import ast

from xcc.aot.analysis import analyze_source
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrBinary,
    IrConstInt,
    IrConstString,
    IrExpr,
    IrFunction,
    IrIntType,
    IrModule,
    IrName,
    IrParam,
    IrReturn,
    IrStmt,
    IrStringType,
    IrType,
)


def lower_source_to_ir(
    source: str,
    *,
    filename: str = "<input>",
    entry: str | None = None,
) -> IrModule:
    analysis = analyze_source(source, filename=filename)
    lowerer = _Lowerer(filename)
    functions = tuple(
        lowerer.lower_function(node)
        for node in analysis.module.tree.body
        if isinstance(node, ast.FunctionDef)
    )
    return IrModule(filename, (), functions, entry=entry)


class _Lowerer:
    def __init__(self, filename: str) -> None:
        self.filename = filename

    def lower_function(self, node: ast.FunctionDef) -> IrFunction:
        params: list[IrParam] = []
        names: dict[str, IrType] = {}
        for arg in node.args.posonlyargs + node.args.args:
            if arg.annotation is None:
                self._error(
                    "XCC-AOT-LOWER-0001",
                    f"Missing lowered parameter annotation: {node.name}.{arg.arg}",
                    arg,
                )
            ir_type = self._annotation_to_ir_type(arg.annotation)
            params.append(IrParam(arg.arg, ir_type))
            names[arg.arg] = ir_type
        return_type = self._annotation_to_ir_type(node.returns)
        body = tuple(
            self._lower_statement(statement, names, return_type) for statement in node.body
        )
        return IrFunction(node.name, tuple(params), return_type, body)

    def _lower_statement(
        self,
        statement: ast.stmt,
        names: dict[str, IrType],
        return_type: IrType,
    ) -> IrStmt:
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
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add | ast.Sub | ast.Mult):
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
            width_type = _width_alias_to_ir_type(name)
            if width_type is not None:
                return width_type
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered annotation: {ast.unparse(annotation)}",
            annotation,
        )

    def _error(self, code: str, message: str, node: ast.AST) -> None:
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
