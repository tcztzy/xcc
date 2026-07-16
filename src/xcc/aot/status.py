from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBreak,
    IrCall,
    IrConstBool,
    IrConstBytes,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrEnumMember,
    IrExpr,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrModule,
    IrName,
    IrPrint,
    IrRaise,
    IrReraise,
    IrReturn,
    IrSetItem,
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrTry,
    IrTuple,
    IrTupleSlice,
    IrWhile,
)

_NORETURN_CALL_PREFIX = "__noreturn__:"
_RECORD_INIT_PREFIX = "__record_init__:"


def analyze_fallibility(module: IrModule) -> frozenset[str]:
    """Return the transitive set of project functions using the status ABI."""
    function_names = {function.name for function in module.functions}
    direct_raises = {
        function.name for function in module.functions if _function_directly_raises(function)
    }
    project_calls = {
        function.name: frozenset(_function_call_targets(function)) & function_names
        for function in module.functions
    }
    fallible = set(direct_raises)
    changed = True
    while changed:
        changed = False
        for function_name, targets in project_calls.items():
            if function_name not in fallible and targets & fallible:
                fallible.add(function_name)
                changed = True
    return frozenset(fallible)


def _function_directly_raises(function: IrFunction) -> bool:
    return any(_statement_directly_raises(statement) for statement in function.body)


def _statement_directly_raises(statement: IrStmt) -> bool:
    if isinstance(statement, IrRaise | IrReraise):
        return True
    if isinstance(statement, IrIf):
        return (
            any(_statement_directly_raises(child) for child in statement.then_branch.statements)
            or statement.else_branch is not None
            and any(_statement_directly_raises(child) for child in statement.else_branch.statements)
        )
    if isinstance(statement, IrForEach | IrWhile):
        return any(_statement_directly_raises(child) for child in statement.body.statements)
    if isinstance(statement, IrTry):
        branches = (
            statement.body,
            statement.orelse,
            statement.finalbody,
            *(handler.body for handler in statement.handlers),
        )
        return any(
            _statement_directly_raises(child) for branch in branches for child in branch.statements
        )
    return False


def _function_call_targets(function: IrFunction) -> set[str]:
    return {target for statement in function.body for target in _statement_call_targets(statement)}


def _statement_call_targets(statement: IrStmt) -> tuple[str, ...]:
    if isinstance(statement, IrAssign):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrSetItem):
        return (
            _expr_call_targets(statement.target)
            + _expr_call_targets(statement.index)
            + _expr_call_targets(statement.value)
        )
    if isinstance(statement, IrReturn):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrIf):
        targets = _expr_call_targets(statement.condition) + _branch_call_targets(
            statement.then_branch.statements
        )
        if statement.else_branch is not None:
            targets += _branch_call_targets(statement.else_branch.statements)
        return targets
    if isinstance(statement, IrForEach):
        return _expr_call_targets(statement.iterable) + _branch_call_targets(
            statement.body.statements
        )
    if isinstance(statement, IrWhile):
        return _expr_call_targets(statement.condition) + _branch_call_targets(
            statement.body.statements
        )
    if isinstance(statement, IrPrint):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrRaise):
        payload_targets = (
            _expr_call_targets(statement.payload) if statement.payload is not None else ()
        )
        return _expr_call_targets(statement.message) + payload_targets
    if isinstance(statement, IrReraise):
        return ()
    if isinstance(statement, IrTry):
        branches = (
            statement.body,
            statement.orelse,
            statement.finalbody,
            *(handler.body for handler in statement.handlers),
        )
        return tuple(
            target for branch in branches for target in _branch_call_targets(branch.statements)
        )
    if isinstance(statement, IrBreak | IrContinue):
        return ()
    # LLVM emission owns malformed-IR diagnostics. Pre-analysis must not mask
    # its stable diagnostic when a validation test supplies an unknown node.
    return ()


def _branch_call_targets(statements: tuple[IrStmt, ...]) -> tuple[str, ...]:
    return tuple(
        target for statement in statements for target in _statement_call_targets(statement)
    )


def _expr_call_targets(expr: IrExpr) -> tuple[str, ...]:
    if isinstance(
        expr,
        IrConstInt
        | IrConstBytes
        | IrConstString
        | IrConstFloat
        | IrConstBool
        | IrConstNone
        | IrEnumMember
        | IrName,
    ):
        return ()
    if isinstance(expr, IrBinary):
        return _expr_call_targets(expr.left) + _expr_call_targets(expr.right)
    if isinstance(expr, IrGetField):
        return _expr_call_targets(expr.value)
    if isinstance(expr, IrConstructRecord):
        return _expr_tuple_call_targets(expr.args)
    if isinstance(expr, IrCall):
        if expr.target.startswith(_NORETURN_CALL_PREFIX):
            return (expr.target.removeprefix(_NORETURN_CALL_PREFIX),) + _expr_tuple_call_targets(
                expr.args
            )
        if expr.target.startswith(_RECORD_INIT_PREFIX):
            return (expr.target.removeprefix(_RECORD_INIT_PREFIX),) + _expr_tuple_call_targets(
                expr.args
            )
        return (expr.target,) + _expr_tuple_call_targets(expr.args)
    if isinstance(expr, IrTuple):
        return _expr_tuple_call_targets(expr.elements)
    if isinstance(expr, IrTupleSlice):
        return (
            _expr_call_targets(expr.value)
            + (_expr_call_targets(expr.start) if expr.start is not None else ())
            + (_expr_call_targets(expr.stop) if expr.stop is not None else ())
        )
    if isinstance(expr, IrStringConcat):
        return _expr_tuple_call_targets(expr.parts)
    if isinstance(expr, IrStringJoin):
        return _expr_call_targets(expr.separator) + _expr_call_targets(expr.values)
    # See _statement_call_targets: validation remains the emitter's boundary.
    return ()


def _expr_tuple_call_targets(expressions: tuple[IrExpr, ...]) -> tuple[str, ...]:
    return tuple(target for expression in expressions for target in _expr_call_targets(expression))
