import re
from typing import NoReturn

from .common import PreprocessorError, _SourceLocation
from .expressions import _strip_condition_comments

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_STDC_PRAGMA_TOGGLE_VALUES = frozenset({"ON", "OFF", "DEFAULT"})
_STDC_VALIDATED_PRAGMAS = frozenset({"FENV_ACCESS", "CX_LIMITED_RANGE", "FP_CONTRACT"})
_STDC_FENV_ROUND_VALUES = frozenset(
    {"FE_DYNAMIC", "FE_DOWNWARD", "FE_TONEAREST", "FE_TOWARDZERO", "FE_UPWARD"}
)
_DIAGNOSTIC_PRAGMA_ACTIONS = frozenset({"error", "warning", "ignored", "fatal", "push", "pop"})
_MODULE_NAME_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_PRAGMA_FP_OPTION_RE = re.compile(r"([A-Za-z_]\w*)\s*\(([^()]*)\)")
_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def _raise_pragma_error(message: str, location: _SourceLocation) -> NoReturn:
    raise PreprocessorError(
        message,
        location.line,
        1,
        filename=location.filename,
        code="XCC-PP-0104",
    )


def _validate_defined_syntax(expr: str, location: _SourceLocation) -> None:
    cursor = 0
    while True:
        match = re.search(r"\bdefined\b", expr[cursor:])
        if match is None:
            return
        cursor += match.end()
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
    if not operand or _IDENT_RE.fullmatch(operand) is None:
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
    if _STRING_LITERAL_RE.fullmatch(remainder) is None:
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
    match = _MODULE_NAME_RE.match(remainder)
    if match is not None:
        if remainder[match.end() :].strip():
            _raise_pragma_error("Invalid #pragma clang module directive", location)
        return
    _raise_pragma_error("Invalid #pragma clang module directive", location)


def _validate_clang_fp_pragma(body: str, location: _SourceLocation) -> None:
    if not body.startswith("clang fp"):
        return
    tail = body.removeprefix("clang fp").strip()
    for match in _PRAGMA_FP_OPTION_RE.finditer(tail):
        if match.group(1) not in {"reassociate", "reciprocal"}:
            continue
        if match.group(2).strip() not in {"on", "off"}:
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
