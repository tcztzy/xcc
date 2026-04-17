from xcc.ast import Expr
from xcc.types import Type

from .symbols import Scope, SemaError


def check_call_arguments(
    analyzer: object,
    args: list[Expr],
    parameter_types: tuple[Type, ...] | None,
    is_variadic: bool,
    function_name: str | None,
    scope: Scope,
) -> None:
    if parameter_types is None:
        return
    if (not is_variadic and len(args) != len(parameter_types)) or (
        is_variadic and len(args) < len(parameter_types)
    ):
        suffix = f": {function_name}" if function_name is not None else ""
        expected = len(parameter_types)
        got = len(args)
        if is_variadic:
            raise SemaError(
                f"Argument count mismatch (expected at least {expected}, got {got}){suffix}"
            )
        raise SemaError(f"Argument count mismatch (expected {expected}, got {got}){suffix}")
    for index, arg in enumerate(args[: len(parameter_types)]):
        arg_type = analyzer._type_map.require(arg)  # type: ignore[attr-defined]
        value_arg_type = analyzer._decay_array_value(arg_type)  # type: ignore[attr-defined]
        if not analyzer._is_assignment_expr_compatible(  # type: ignore[attr-defined]
            parameter_types[index],
            arg,
            value_arg_type,
            scope,
        ):
            suffix = f": {function_name}" if function_name is not None else ""
            raise SemaError(f"Argument {index + 1} type mismatch{suffix}")
