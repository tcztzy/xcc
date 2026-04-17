import re
from collections.abc import Callable
from pathlib import Path

from .common import PreprocessorError, _SourceLocation

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SCOPED_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*")
_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def _raise_probe_error(
    marker: str,
    message: str,
    location: _SourceLocation,
    *,
    code: str,
) -> None:
    raise PreprocessorError(
        f"Invalid {marker} expression: {message}",
        location.line,
        1,
        filename=location.filename,
        code=code,
    )


def _find_matching_has_include_close(expr: str, open_paren: int) -> int:
    depth = 0
    index = open_paren
    while index < len(expr):
        char = expr[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _replace_probe_operator(
    expr: str,
    *,
    marker: str,
    location: _SourceLocation,
    missing_operand_message: str,
    code: str,
    rewrite_operand: Callable[[str], str],
) -> str:
    chunks: list[str] = []
    index = 0
    while True:
        found = expr.find(marker, index)
        if found < 0:
            chunks.append(expr[index:])
            return "".join(chunks)
        prev = expr[found - 1] if found > 0 else ""
        next_pos = found + len(marker)
        next_char = expr[next_pos] if next_pos < len(expr) else ""
        if (prev and (prev.isalnum() or prev == "_")) or (
            next_char and (next_char.isalnum() or next_char == "_")
        ):
            chunks.append(expr[index : found + len(marker)])
            index = found + len(marker)
            continue

        chunks.append(expr[index:found])
        cursor = next_pos
        while cursor < len(expr) and expr[cursor].isspace():
            cursor += 1
        if cursor >= len(expr) or expr[cursor] != "(":
            _raise_probe_error(marker, "expected '(' after operator", location, code=code)
        close_paren = _find_matching_has_include_close(expr, cursor)
        if close_paren < 0:
            _raise_probe_error(marker, "missing closing ')'", location, code=code)

        operand = expr[cursor + 1 : close_paren].strip()
        if not operand:
            _raise_probe_error(marker, missing_operand_message, location, code=code)

        chunks.append(rewrite_operand(operand))
        index = close_paren + 1


def _replace_single_feature_probe_operator(
    expr: str,
    *,
    marker: str,
    location: _SourceLocation,
    supported: tuple[str, ...],
    code: str,
) -> str:
    supported_names = frozenset(supported)

    def rewrite_operand(operand: str) -> str:
        if _IDENT_RE.fullmatch(operand) is None:
            _raise_probe_error(
                marker,
                "feature operand must be an identifier",
                location,
                code=code,
            )
        return "1" if operand in supported_names else "0"

    return _replace_probe_operator(
        expr,
        marker=marker,
        location=location,
        missing_operand_message="missing feature operand",
        code=code,
        rewrite_operand=rewrite_operand,
    )


def _replace_single_warning_probe_operator(
    expr: str,
    *,
    marker: str,
    location: _SourceLocation,
    supported: frozenset[str],
    code: str,
) -> str:
    def rewrite_operand(operand: str) -> str:
        if _STRING_LITERAL_RE.fullmatch(operand) is None:
            _raise_probe_error(
                marker,
                "warning option operand must be a string literal",
                location,
                code=code,
            )
        return "1" if operand[1:-1] in supported else "0"

    return _replace_probe_operator(
        expr,
        marker=marker,
        location=location,
        missing_operand_message="missing warning option operand",
        code=code,
        rewrite_operand=rewrite_operand,
    )


def _replace_single_attribute_probe_operator(
    expr: str,
    *,
    marker: str,
    location: _SourceLocation,
    supported: frozenset[str],
    code: str,
) -> str:
    def rewrite_operand(operand: str) -> str:
        if _SCOPED_IDENT_RE.fullmatch(operand) is None:
            _raise_probe_error(
                marker,
                "attribute operand must be an identifier or scoped identifier",
                location,
                code=code,
            )
        return "1" if operand in supported else "0"

    return _replace_probe_operator(
        expr,
        marker=marker,
        location=location,
        missing_operand_message="missing attribute operand",
        code=code,
        rewrite_operand=rewrite_operand,
    )


def _replace_single_has_include_operator(
    expr: str,
    *,
    marker: str,
    location: _SourceLocation,
    base_dir: Path | None,
    include_next: bool,
    parse_header_name_operand: Callable[[str, _SourceLocation], tuple[str, bool]],
    resolve_include: Callable[..., tuple[Path | None, tuple[Path, ...]]],
    code: str,
) -> str:
    def rewrite_operand(operand: str) -> str:
        try:
            include_name, is_angled = parse_header_name_operand(operand, location)
        except PreprocessorError as error:
            raise PreprocessorError(
                f"Invalid {marker} expression: header operand must be quoted or angled",
                location.line,
                1,
                filename=location.filename,
                code=code,
            ) from error
        include_path, _ = resolve_include(
            include_name,
            is_angled=is_angled,
            base_dir=base_dir,
            include_next_from=base_dir if include_next else None,
        )
        return "1" if include_path is not None else "0"

    return _replace_probe_operator(
        expr,
        marker=marker,
        location=location,
        missing_operand_message="missing header operand",
        code=code,
        rewrite_operand=rewrite_operand,
    )


def _replace_feature_probe_operators(
    expr: str,
    *,
    location: _SourceLocation,
    supported_warnings: frozenset[str],
    supported_c_attributes: frozenset[str],
    code: str,
) -> str:
    rewritten = expr
    for marker in ("__has_builtin", "__has_attribute", "__has_feature", "__has_extension"):
        rewritten = _replace_single_feature_probe_operator(
            rewritten,
            marker=marker,
            location=location,
            supported=(),
            code=code,
        )
    rewritten = _replace_single_warning_probe_operator(
        rewritten,
        marker="__has_warning",
        location=location,
        supported=supported_warnings,
        code=code,
    )
    return _replace_single_attribute_probe_operator(
        rewritten,
        marker="__has_c_attribute",
        location=location,
        supported=supported_c_attributes,
        code=code,
    )


def _replace_has_include_operators(
    expr: str,
    *,
    location: _SourceLocation,
    base_dir: Path | None,
    parse_header_name_operand: Callable[[str, _SourceLocation], tuple[str, bool]],
    resolve_include: Callable[..., tuple[Path | None, tuple[Path, ...]]],
    code: str,
) -> str:
    rewritten = _replace_single_has_include_operator(
        expr,
        marker="__has_include_next",
        location=location,
        base_dir=base_dir,
        include_next=True,
        parse_header_name_operand=parse_header_name_operand,
        resolve_include=resolve_include,
        code=code,
    )
    return _replace_single_has_include_operator(
        rewritten,
        marker="__has_include",
        location=location,
        base_dir=base_dir,
        include_next=False,
        parse_header_name_operand=parse_header_name_operand,
        resolve_include=resolve_include,
        code=code,
    )
