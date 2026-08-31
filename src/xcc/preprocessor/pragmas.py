from typing import NoReturn

from .expressions import _strip_condition_comments
from .model import PreprocessorError, _SourceLocation

_STDC_PRAGMA_TOGGLE_VALUES = ("ON", "OFF", "DEFAULT")
_STDC_VALIDATED_PRAGMAS = ("FENV_ACCESS", "CX_LIMITED_RANGE", "FP_CONTRACT")
_STDC_FENV_ROUND_VALUES = (
    "FE_DYNAMIC",
    "FE_DOWNWARD",
    "FE_TONEAREST",
    "FE_TOWARDZERO",
    "FE_UPWARD",
)
_DIAGNOSTIC_PRAGMA_ACTIONS = ("error", "warning", "ignored", "fatal", "push", "pop")
_DEFINED_OPERATOR = "defined"


def _raise_pragma_error(message: str, location: _SourceLocation) -> NoReturn:
    raise PreprocessorError(
        message,
        location.line,
        1,
        filename=location.filename,
        code="XCC-PP-0104",
    )


def _is_pp_identifier_character(ch: str) -> bool:
    return ch == "_" or ch.isalnum()


def _is_identifier_start(ch: str) -> bool:
    return ch == "_" or "A" <= ch <= "Z" or "a" <= ch <= "z"


def _is_identifier_char(ch: str) -> bool:
    return _is_identifier_start(ch) or "0" <= ch <= "9"


def _is_identifier(text: str) -> bool:
    if not text or not _is_identifier_start(text[0]):
        return False
    for ch in text[1:]:  # noqa: SIM110 - avoid generator lowering in AOT code.
        if not _is_identifier_char(ch):
            return False
    return True


def _module_name_prefix_end(text: str) -> int | None:
    if not text or not _is_identifier_start(text[0]):
        return None
    cursor = 0
    while True:
        if cursor >= len(text) or not _is_identifier_start(text[cursor]):
            return None
        cursor += 1
        while cursor < len(text) and _is_identifier_char(text[cursor]):
            cursor += 1
        if cursor >= len(text) or text[cursor] != ".":
            return cursor
        cursor += 1


def _is_string_literal(text: str) -> bool:
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        return False
    cursor = 1
    while cursor < len(text) - 1:
        ch = text[cursor]
        if ch == "\n" or ch == '"':
            return False
        if ch == "\\":
            cursor += 1
            if cursor >= len(text) - 1 or text[cursor] == "\n":
                return False
        cursor += 1
    return True


def _pragma_fp_options(text: str) -> tuple[tuple[str, str], ...]:
    options: tuple[tuple[str, str], ...] = ()
    cursor = 0
    while cursor < len(text):
        if not _is_identifier_start(text[cursor]):
            cursor += 1
            continue
        name_start = cursor
        cursor += 1
        while cursor < len(text) and _is_identifier_char(text[cursor]):
            cursor += 1
        name = text[name_start:cursor]
        arg_start = cursor
        while arg_start < len(text) and text[arg_start].isspace():
            arg_start += 1
        if arg_start >= len(text) or text[arg_start] != "(":
            continue
        arg_cursor = arg_start + 1
        while arg_cursor < len(text) and text[arg_cursor] not in "()":
            arg_cursor += 1
        if arg_cursor >= len(text) or text[arg_cursor] != ")":
            cursor = arg_start + 1
            continue
        options = (*options, (name, text[arg_start + 1 : arg_cursor]))
        cursor = arg_cursor + 1
    return options


def _find_defined_operator_end(expr: str, cursor: int) -> int | None:
    while True:
        start = expr.find(_DEFINED_OPERATOR, cursor)
        if start < 0:
            return None
        end = start + len(_DEFINED_OPERATOR)
        has_leading_boundary = start == 0 or not _is_pp_identifier_character(expr[start - 1])
        has_trailing_boundary = end == len(expr) or not _is_pp_identifier_character(expr[end])
        if has_leading_boundary and has_trailing_boundary:
            return end
        cursor = end


def _validate_defined_syntax(expr: str, location: _SourceLocation) -> None:
    cursor = 0
    while True:
        defined_end = _find_defined_operator_end(expr, cursor)
        if defined_end is None:
            return
        cursor = defined_end
        while cursor < len(expr) and expr[cursor].isspace():
            cursor += 1
        if cursor >= len(expr) or expr[cursor] != "(":
            continue
        if ")" not in expr[cursor + 1 :]:
            raise PreprocessorError(
                "Invalid #if expression",
                location.line,
                1,
                filename=location.filename,
                code="XCC-PP-0103",
            )
        cursor += 1


def _validate_stdc_pragma(body: str, location: _SourceLocation) -> None:
    parts = body.split()
    if len(parts) < 2:
        return
    subject = parts[1]
    value = " ".join(parts[2:])
    if subject == "FENV_ROUND":
        if value not in _STDC_FENV_ROUND_VALUES:
            _raise_pragma_error(
                f"Invalid #pragma STDC FENV_ROUND value: {value or '<missing>'}",
                location,
            )
        return
    if subject not in _STDC_VALIDATED_PRAGMAS:
        return
    if value not in _STDC_PRAGMA_TOGGLE_VALUES:
        _raise_pragma_error(
            f"Invalid #pragma STDC {subject} value: {value or '<missing>'}",
            location,
        )


def _validate_gcc_visibility_pragma(body: str, location: _SourceLocation) -> None:
    if not body.startswith("GCC visibility"):
        return
    tail = body.removeprefix("GCC visibility").strip()
    if tail == "pop":
        return
    if not tail.startswith("push"):
        _raise_pragma_error("Invalid #pragma GCC visibility directive", location)
    arguments = tail.removeprefix("push").strip()
    if not arguments.startswith("(") or not arguments.endswith(")"):
        _raise_pragma_error("Invalid #pragma GCC visibility directive", location)
    operand = arguments[1:-1].strip()
    if not _is_identifier(operand):
        _raise_pragma_error("Invalid #pragma GCC visibility directive", location)


def _validate_fenv_access_pragma(body: str, location: _SourceLocation) -> None:
    if not body.startswith("fenv_access"):
        return
    arguments = body.removeprefix("fenv_access").strip()
    if not arguments.startswith("(") or not arguments.endswith(")"):
        _raise_pragma_error("Invalid #pragma fenv_access directive", location)
    operand = arguments[1:-1].strip().lower()
    if operand not in {"on", "off"}:
        _raise_pragma_error("Invalid #pragma fenv_access directive", location)


def _validate_diagnostic_pragma(body: str, location: _SourceLocation) -> None:
    prefix = ""
    if body.startswith("clang diagnostic"):
        prefix = "clang diagnostic"
    elif body.startswith("GCC diagnostic"):
        prefix = "GCC diagnostic"
    if not prefix:
        return
    tail = body.removeprefix(prefix).strip()
    if not tail:
        _raise_pragma_error("Invalid #pragma diagnostic directive", location)
    parts = tail.split(None, 1)
    action = parts[0]
    if action not in _DIAGNOSTIC_PRAGMA_ACTIONS:
        _raise_pragma_error("Invalid #pragma diagnostic directive", location)
    remainder = parts[1].strip() if len(parts) == 2 else ""
    if action in {"push", "pop"}:
        if remainder:
            _raise_pragma_error("Invalid #pragma diagnostic directive", location)
        return
    if not _is_string_literal(remainder):
        _raise_pragma_error("Invalid #pragma diagnostic directive", location)
    if not remainder.startswith('"-W'):
        _raise_pragma_error("Invalid #pragma diagnostic directive", location)


def _validate_clang_module_pragma(body: str, location: _SourceLocation) -> None:
    if not body.startswith("clang module"):
        return
    tail = body.removeprefix("clang module").strip()
    if not tail:
        return
    parts = tail.split(None, 1)
    action = parts[0]
    if action not in {"import", "begin", "end"}:
        return
    remainder = parts[1].strip() if len(parts) == 2 else ""
    if action == "end":
        if remainder:
            _raise_pragma_error("Invalid #pragma clang module directive", location)
        return
    if not remainder:
        _raise_pragma_error("Invalid #pragma clang module directive", location)
    module_name_end = _module_name_prefix_end(remainder)
    if module_name_end is not None:
        if remainder[module_name_end:].strip():
            _raise_pragma_error("Invalid #pragma clang module directive", location)
        return
    _raise_pragma_error("Invalid #pragma clang module directive", location)


def _validate_clang_fp_pragma(body: str, location: _SourceLocation) -> None:
    if not body.startswith("clang fp"):
        return
    tail = body.removeprefix("clang fp").strip()
    for name, value in _pragma_fp_options(tail):
        if name not in {"reassociate", "reciprocal"}:
            continue
        if value.strip() not in {"on", "off"}:
            _raise_pragma_error("Invalid #pragma clang fp directive", location)


def _validate_pragma(body: str, location: _SourceLocation) -> None:
    body = _strip_condition_comments(body).strip()
    if body.startswith("STDC "):
        _validate_stdc_pragma(body, location)
        return
    if body.startswith("GCC visibility"):
        _validate_gcc_visibility_pragma(body, location)
        return
    if body.startswith("fenv_access"):
        _validate_fenv_access_pragma(body, location)
        return
    _validate_diagnostic_pragma(body, location)
    _validate_clang_module_pragma(body, location)
    _validate_clang_fp_pragma(body, location)
