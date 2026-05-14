"""Printf format string checking."""

from dataclasses import dataclass

from xcc.ast import Expr, StringLiteral
from xcc.types import Type

from .constants import decode_escaped_units, string_literal_body
from .symbols import Scope, SemaError
from .type_helpers import is_floating_type, is_integer_type


@dataclass
class _FormatSpec:
    length: str | None = None
    conversion: str = ""
    has_flags: bool = False
    width_arg: bool = False
    precision_arg: bool = False


def _parse_printf_format_string(s: str) -> list[_FormatSpec]:
    specs: list[_FormatSpec] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] != "%":
            i += 1
            continue
        i += 1
        if i >= n:  # pragma: no cover
            break
        if s[i] == "%":
            i += 1
            continue
        spec = _FormatSpec()
        while i < n and s[i] in "-+ #0'":  # pragma: no branch
            spec.has_flags = True
            i += 1
        if i < n and s[i] == "*":  # pragma: no cover
            spec.width_arg = True
            i += 1
        elif i < n and s[i].isdigit():  # pragma: no cover
            while i < n and s[i].isdigit():
                i += 1
        if i < n and s[i] == ".":  # pragma: no branch
            i += 1
            if i < n and s[i] == "*":  # pragma: no cover
                spec.precision_arg = True
                i += 1
            elif i < n and s[i].isdigit():  # pragma: no cover
                while i < n and s[i].isdigit():
                    i += 1
        if i + 1 < n and s[i : i + 2] in {"hh", "ll"}:  # pragma: no cover
            spec.length = s[i : i + 2]
            i += 2
        elif i < n and s[i] in "hljztL":  # pragma: no branch
            spec.length = s[i]
            i += 1
        if i < n:  # pragma: no branch
            spec.conversion = s[i]
            i += 1
        specs.append(spec)
    return specs


def _format_flag_msg(arg_index: int, arg_type_str: str, expected: str) -> str:
    return f"format specifies type '{expected}' but the argument has type '{arg_type_str}'"


def check_printf_format(
    analyzer: object,
    format_expr: Expr,
    variadic_args: list[Expr],
    scope: Scope,
) -> None:
    if not isinstance(format_expr, StringLiteral):
        return  # pragma: no cover
    body = string_literal_body(format_expr.value)
    if body is None:  # pragma: no cover
        return
    decoded = decode_escaped_units(body)
    format_string = "".join(chr(c) for c in decoded)
    specs = _parse_printf_format_string(format_string)
    arg_index = 0
    for spec in specs:  # pragma: no branch
        if spec.width_arg:  # pragma: no cover
            arg_index += 1
        if spec.precision_arg:  # pragma: no cover
            arg_index += 1
        if arg_index >= len(variadic_args):  # pragma: no cover
            break
        arg_type = analyzer._type_map.require(variadic_args[arg_index])  # type: ignore[attr-defined]
        _check_format_spec(spec, arg_type, arg_index + 1)
        arg_index += 1


def _pointee_or_element(type_: Type) -> Type | None:
    if (pointee := type_.pointee()) is not None:
        return pointee
    return type_.element_type()


def _check_format_spec(spec: _FormatSpec, arg_type: Type, arg_index: int) -> None:
    c = spec.conversion.lower()
    if c in "diuox":  # pragma: no branch
        if not is_integer_type(arg_type):
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "integer"))
    elif c in "feag":  # pragma: no branch
        if not is_floating_type(arg_type):
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "floating-point"))
    elif c == "c":
        if not is_integer_type(arg_type):  # pragma: no cover
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "integer"))
    elif c == "s":
        pointee = _pointee_or_element(arg_type)
        if pointee is None:  # pragma: no cover
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "pointer to char"))
        if pointee.name not in {"char", "signed char", "unsigned char"}:  # pragma: no cover
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "pointer to char"))
    elif c == "p":
        pointee = _pointee_or_element(arg_type)
        if pointee is None:  # pragma: no cover
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "pointer"))
    elif c == "n":  # pragma: no branch
        pointee = _pointee_or_element(arg_type)
        if pointee is None or not is_integer_type(pointee):  # pragma: no cover
            raise SemaError(_format_flag_msg(arg_index, str(arg_type), "pointer to integer"))
