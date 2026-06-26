from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBranch,
    IrCall,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrExpr,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrPrint,
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
)
from xcc.aot.lower import lower_source_to_ir

_NATIVE_EMITTED_LEAF_FUNCTIONS = {"xcc.types.Type.__str__"}


@dataclass(frozen=True)
class AotSliceInput:
    name: str
    path: Path


def collect_slice_inputs(paths: tuple[Path, ...]) -> tuple[AotSliceInput, ...]:
    root = (Path.cwd() / "src" / "xcc").resolve()
    modules: list[AotSliceInput] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is outside src/xcc: {resolved}",
                        filename=str(resolved),
                    ),
                )
            ) from exc
        if relative.suffix != ".py":
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is not Python source: {resolved}",
                        filename=str(resolved),
                    ),
                )
            )
        modules.append(AotSliceInput("xcc." + ".".join(relative.with_suffix("").parts), resolved))
    return tuple(sorted(modules, key=lambda module: module.name))


def lower_core_slice(paths: tuple[Path, ...]) -> IrModule:
    records: list[IrRecord] = []
    functions: list[IrFunction] = []
    for module_input in collect_slice_inputs(paths):
        source = module_input.path.read_text(encoding="utf-8")
        module = lower_source_to_ir(source, filename=str(module_input.path))
        records.extend(module.records)
        prefix = module_input.name
        rename_map = {function.name: f"{prefix}.{function.name}" for function in module.functions}
        for function in module.functions:
            functions.append(
                IrFunction(
                    rename_map[function.name],
                    function.params,
                    function.return_type,
                    _rename_statement_calls(function.body, rename_map),
                )
            )
    return IrModule("<core-slice>", tuple(records), tuple(functions))


def core_slice_entry_module(module: IrModule, wrapper: IrFunction) -> IrModule:
    functions_by_name = {function.name: function for function in module.functions}
    reachable: set[str] = set()
    pending = list(_function_call_targets(wrapper))
    while pending:
        target = pending.pop()
        if target in reachable:
            continue
        function = functions_by_name.get(target)
        if function is None:
            continue
        reachable.add(target)
        if function.name in _NATIVE_EMITTED_LEAF_FUNCTIONS:
            continue
        pending.extend(_function_call_targets(function))
    return IrModule(
        module.filename,
        module.records,
        tuple(function for function in module.functions if function.name in reachable) + (wrapper,),
        entry=wrapper.name,
    )


def core_entry_wrapper(entry: str, fixture: str) -> IrFunction:
    if entry == "xcc.diag:Diagnostic.__str__" and fixture == "diag_with_location":
        return _diagnostic_str_wrapper()
    if entry == "xcc.options:FrontendOptions.__post_init__" and fixture == "bad_std":
        return _frontend_options_bad_std_wrapper()
    if entry == "xcc.types:Type.pointer_array_str" and fixture == "int_pointer_array":
        return _type_pointer_array_str_wrapper()
    if entry == "xcc.lexer:translate_source" and fixture == "trigraph_splice":
        return _lexer_translate_source_wrapper()
    if entry == "xcc.lexer:lex" and fixture == "simple_declaration":
        return _lexer_lex_simple_declaration_wrapper()
    if entry == "xcc.lexer:lex_pp" and fixture == "header_name":
        return _lexer_header_name_wrapper()
    if entry == "xcc.lexer:lex_error" and fixture == "unterminated_string":
        return _lexer_unterminated_string_wrapper()
    raise AotError(
        (
            AotDiagnostic(
                "XCC-AOT-SLICE-0002",
                f"Unsupported core entry fixture: {entry} / {fixture}",
                filename="<core-slice>",
            ),
        )
    )


def _diagnostic_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    diagnostic_type = IrRecordType("Diagnostic")
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(
                IrCall(
                    "xcc.diag.Diagnostic.__str__",
                    (
                        IrConstructRecord(
                            "Diagnostic",
                            (
                                IrConstString("parse"),
                                IrConstString("input.c"),
                                IrConstString("expected ';'"),
                                IrConstInt(7, IrIntType(64, signed=True)),
                                IrConstInt(3, IrIntType(64, signed=True)),
                                IrConstNone(),
                            ),
                            diagnostic_type,
                        ),
                    ),
                    IrStringType(),
                ),
            ),
            IrReturn(IrConstInt(0, int32)),
        ),
    )


def _lexer_translate_source_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer.translate_source",
        (IrConstString("int??=x\\\n=1;"),),
    )


def _lexer_lex_simple_declaration_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer._aot_token_summary_for_source",
        (IrConstString("int main() { return 0; }"),),
    )


def _lexer_header_name_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer._aot_header_summary_for_source",
        (IrConstString("<stdio.h>"),),
    )


def _lexer_unterminated_string_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer._aot_error_summary_for_source",
        (IrConstString('"'),),
        status=2,
    )


def _string_call_wrapper(
    target: str,
    args: tuple[IrExpr, ...],
    *,
    status: int = 0,
) -> IrFunction:
    int32 = IrIntType(32, signed=True)
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(IrCall(target, args, IrStringType())),
            IrReturn(IrConstInt(status, int32)),
        ),
    )


def _rename_statement_calls(
    statements: tuple[IrStmt, ...],
    rename_map: dict[str, str],
) -> tuple[IrStmt, ...]:
    return tuple(_rename_statement_call(statement, rename_map) for statement in statements)


def _rename_statement_call(statement: IrStmt, rename_map: dict[str, str]) -> IrStmt:
    if isinstance(statement, IrAssign):
        return IrAssign(statement.target, _rename_expr_call(statement.value, rename_map))
    if isinstance(statement, IrReturn):
        return IrReturn(_rename_expr_call(statement.value, rename_map))
    if isinstance(statement, IrIf):
        return IrIf(
            _rename_expr_call(statement.condition, rename_map),
            _rename_branch_calls(statement.then_branch, rename_map),
            (
                _rename_branch_calls(statement.else_branch, rename_map)
                if statement.else_branch is not None
                else None
            ),
        )
    if isinstance(statement, IrForEach):
        return IrForEach(
            statement.target,
            _rename_expr_call(statement.iterable, rename_map),
            _rename_branch_calls(statement.body, rename_map),
        )
    if isinstance(statement, IrPrint):
        return IrPrint(_rename_expr_call(statement.value, rename_map))
    if isinstance(statement, IrRaise):
        return IrRaise(statement.exception, _rename_expr_call(statement.message, rename_map))
    assert_never(statement)


def _rename_branch_calls(branch: IrBranch, rename_map: dict[str, str]) -> IrBranch:
    return IrBranch(_rename_statement_calls(branch.statements, rename_map))


def _rename_expr_call(expr: IrExpr, rename_map: dict[str, str]) -> IrExpr:
    if isinstance(
        expr,
        IrConstInt | IrConstString | IrConstBool | IrConstNone | IrName,
    ):
        return expr
    if isinstance(expr, IrBinary):
        return IrBinary(
            expr.op,
            _rename_expr_call(expr.left, rename_map),
            _rename_expr_call(expr.right, rename_map),
            expr.type,
        )
    if isinstance(expr, IrGetField):
        return IrGetField(_rename_expr_call(expr.value, rename_map), expr.field, expr.type)
    if isinstance(expr, IrConstructRecord):
        return IrConstructRecord(
            expr.record,
            tuple(_rename_expr_call(arg, rename_map) for arg in expr.args),
            expr.type,
        )
    if isinstance(expr, IrCall):
        return IrCall(
            rename_map.get(expr.target, expr.target),
            tuple(_rename_expr_call(arg, rename_map) for arg in expr.args),
            expr.type,
        )
    if isinstance(expr, IrTuple):
        return IrTuple(
            tuple(_rename_expr_call(element, rename_map) for element in expr.elements),
            expr.type,
        )
    if isinstance(expr, IrTupleSlice):
        return IrTupleSlice(_rename_expr_call(expr.value, rename_map), expr.start, expr.stop)
    if isinstance(expr, IrStringConcat):
        return IrStringConcat(tuple(_rename_expr_call(part, rename_map) for part in expr.parts))
    if isinstance(expr, IrStringJoin):
        return IrStringJoin(
            _rename_expr_call(expr.separator, rename_map),
            _rename_expr_call(expr.values, rename_map),
        )
    assert_never(expr)


def _function_call_targets(function: IrFunction) -> tuple[str, ...]:
    targets: list[str] = []
    for statement in function.body:
        targets.extend(_statement_call_targets(statement))
    return tuple(targets)


def _statement_call_targets(statement: IrStmt) -> tuple[str, ...]:
    if isinstance(statement, IrAssign):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrReturn):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrIf):
        targets = list(_expr_call_targets(statement.condition))
        targets.extend(_branch_call_targets(statement.then_branch))
        if statement.else_branch is not None:
            targets.extend(_branch_call_targets(statement.else_branch))
        return tuple(targets)
    if isinstance(statement, IrForEach):
        return _expr_call_targets(statement.iterable) + _branch_call_targets(statement.body)
    if isinstance(statement, IrPrint):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrRaise):
        return _expr_call_targets(statement.message)
    assert_never(statement)


def _branch_call_targets(branch: IrBranch) -> tuple[str, ...]:
    targets: list[str] = []
    for statement in branch.statements:
        targets.extend(_statement_call_targets(statement))
    return tuple(targets)


def _expr_call_targets(expr: IrExpr) -> tuple[str, ...]:
    if isinstance(
        expr,
        IrConstInt | IrConstString | IrConstBool | IrConstNone | IrName,
    ):
        return ()
    if isinstance(expr, IrBinary):
        return _expr_call_targets(expr.left) + _expr_call_targets(expr.right)
    if isinstance(expr, IrGetField):
        return _expr_call_targets(expr.value)
    if isinstance(expr, IrConstructRecord):
        return _expr_tuple_call_targets(expr.args)
    if isinstance(expr, IrCall):
        return (expr.target,) + _expr_tuple_call_targets(expr.args)
    if isinstance(expr, IrTuple):
        return _expr_tuple_call_targets(expr.elements)
    if isinstance(expr, IrTupleSlice):
        return _expr_call_targets(expr.value)
    if isinstance(expr, IrStringConcat):
        return _expr_tuple_call_targets(expr.parts)
    if isinstance(expr, IrStringJoin):
        return _expr_call_targets(expr.separator) + _expr_call_targets(expr.values)
    assert_never(expr)


def _expr_tuple_call_targets(expressions: tuple[IrExpr, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    for expression in expressions:
        targets.extend(_expr_call_targets(expression))
    return tuple(targets)


def _frontend_options_bad_std_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    options_type = IrRecordType("FrontendOptions")
    string_tuple = IrConstNone()
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrAssign(
                "__expr",
                IrCall(
                    "xcc.options.FrontendOptions.__post_init__",
                    (
                        IrConstructRecord(
                            "FrontendOptions",
                            (
                                IrConstString("c99"),
                                IrConstBool(True),
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                IrConstBool(False),
                                IrConstString("human"),
                                IrConstBool(False),
                                IrConstNone(),
                                IrConstNone(),
                                IrConstBool(True),
                            ),
                            options_type,
                        ),
                    ),
                    IrNoneType(),
                ),
            ),
            IrReturn(IrConstInt(2, int32)),
        ),
    )


def _type_pointer_array_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    int64 = IrIntType(64, signed=True)
    type_type = IrRecordType("Type")
    op_type = IrTupleType((IrStringType(), int64))
    declarator_ops = IrTuple(
        (
            IrTuple((IrConstString("arr"), IrConstInt(4, int64)), op_type),
            IrTuple((IrConstString("ptr"), IrConstInt(0, int64)), op_type),
        ),
        IrTupleType((op_type, op_type)),
    )
    array = IrConstructRecord(
        "Type",
        (
            IrConstString("int"),
            IrConstInt(0, int64),
            IrConstNone(),
            declarator_ops,
            IrConstNone(),
        ),
        type_type,
    )
    rendered = IrCall("xcc.types.Type.__str__", (array,), IrStringType())
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(rendered),
            IrReturn(IrConstInt(0, int32)),
        ),
    )
