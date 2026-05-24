from collections.abc import Callable

from xcc.lexer import Token, TokenKind

_MS_DECLSPEC_KEYWORD = "__declspec"
_MS_CALLING_CONVENTION_IDENTIFIERS = {
    "__cdecl",
    "__stdcall",
    "__fastcall",
    "__thiscall",
    "__vectorcall",
}
_AVAILABILITY_ATTRIBUTE_NAMES = {
    "API_AVAILABLE",
    "API_DEPRECATED",
    "API_UNAVAILABLE",
}
_AVAILABILITY_ATTRIBUTE_SUFFIXES = (
    "_API_AVAILABLE",
    "_API_DEPRECATED",
    "_API_UNAVAILABLE",
)
_EXTENSION_MARKER = "__extension__"


def _skip_extension_markers(parser: object) -> None:
    while parser._check_keyword(_EXTENSION_MARKER):  # type: ignore
        parser._advance()  # type: ignore


def _consume_overloadable_decl_attributes(parser: object) -> bool:
    _, has_overloadable = _consume_decl_attributes(parser)
    return has_overloadable


def _skip_decl_attributes(parser: object) -> bool:
    found, _ = _consume_decl_attributes(parser)
    return found


def _skip_gnu_attributes(parser: object, make_error: Callable[[str, Token], Exception]) -> bool:
    found, _ = _consume_gnu_attributes(parser, make_error)
    return found


def _skip_decl_extensions(parser: object) -> None:
    while _skip_decl_attributes(parser) or _skip_asm_label(parser):
        pass


def _consume_decl_attributes(parser: object) -> tuple[bool, bool]:
    found, has_overloadable, _, _ = _consume_decl_attributes_with_alignment(parser)
    return found, has_overloadable


def _consume_decl_attribute_alignment(parser: object) -> tuple[bool, int | None, Token | None]:
    found, _, alignment, alignment_token = _consume_decl_attributes_with_alignment(parser)
    return found, alignment, alignment_token


def _consume_decl_attributes_with_alignment(
    parser: object,
) -> tuple[bool, bool, int | None, Token | None]:
    found = False
    has_overloadable = False
    alignment: int | None = None
    alignment_token: Token | None = None
    while True:
        (
            gnu_found,
            gnu_has_overloadable,
            gnu_alignment,
            gnu_alignment_token,
        ) = _consume_gnu_attributes_with_alignment(
            parser,
            parser._make_error,  # type: ignore
        )
        ms_found = _skip_ms_declspecs(
            parser,
            parser._make_error,  # type: ignore
        )
        availability_found = _skip_availability_attributes(
            parser,
            parser._make_error,  # type: ignore
        )
        found = found or gnu_found or ms_found or availability_found
        has_overloadable = has_overloadable or gnu_has_overloadable
        if gnu_alignment is not None and (alignment is None or gnu_alignment > alignment):
            alignment = gnu_alignment
            alignment_token = gnu_alignment_token
        if not gnu_found and not ms_found and not availability_found:
            break
    return found, has_overloadable, alignment, alignment_token


def _consume_gnu_attributes(
    parser: object,
    make_error: Callable[[str, Token], Exception],
) -> tuple[bool, bool]:
    found, has_overloadable, _, _ = _consume_gnu_attributes_with_alignment(
        parser,
        make_error,
    )
    return found, has_overloadable


def _consume_gnu_attributes_with_alignment(
    parser: object,
    make_error: Callable[[str, Token], Exception],
) -> tuple[bool, bool, int | None, Token | None]:
    found = False
    has_overloadable = False
    alignment: int | None = None
    alignment_token: Token | None = None
    while _is_gnu_attribute_start(parser):
        start = parser._advance()  # type: ignore
        parser._expect_punct("(")  # type: ignore
        parser._expect_punct("(")  # type: ignore
        depth = 2
        while depth > 0:
            token = parser._current()  # type: ignore
            if token.kind == TokenKind.EOF:
                raise make_error("Expected ')'", start)
            if token.kind == TokenKind.IDENT and token.lexeme == "overloadable":
                has_overloadable = True
            if (
                depth == 2
                and token.kind == TokenKind.IDENT
                and token.lexeme in {"aligned", "__aligned__"}
                and parser._peek_punct("(")  # type: ignore
            ):
                attr_token = token
                parser._advance()  # type: ignore
                parser._expect_punct("(")  # type: ignore
                if parser._check_punct(")"):  # type: ignore
                    parser._advance()  # type: ignore
                    found = True
                    continue
                expr = parser._parse_conditional()  # type: ignore
                parsed_alignment = parser._eval_array_size_expr(expr)  # type: ignore
                if parsed_alignment is None:
                    raise make_error(
                        "Invalid alignment attribute: argument must be an "
                        "integer constant expression",
                        attr_token,
                    )
                if parsed_alignment <= 0:
                    raise make_error(
                        "Invalid alignment attribute: argument must be positive",
                        attr_token,
                    )
                if (parsed_alignment & (parsed_alignment - 1)) != 0:
                    raise make_error(
                        "Invalid alignment attribute: argument must evaluate to a power of two",
                        attr_token,
                    )
                if alignment is None or parsed_alignment > alignment:
                    alignment = parsed_alignment
                    alignment_token = attr_token
                parser._expect_punct(")")  # type: ignore
                found = True
                continue
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()  # type: ignore
        found = True
    return found, has_overloadable, alignment, alignment_token


def _is_gnu_attribute_start(parser: object) -> bool:
    token = parser._current()  # type: ignore
    if token.kind != TokenKind.IDENT or token.lexeme != "__attribute__":
        return False
    first = parser._peek(1)  # type: ignore
    second = parser._peek(2)  # type: ignore
    return (
        first.kind == TokenKind.PUNCTUATOR
        and first.lexeme == "("
        and second.kind == TokenKind.PUNCTUATOR
        and second.lexeme == "("
    )


def _skip_ms_declspecs(
    parser: object,
    make_error: Callable[[str, Token], Exception],
) -> bool:
    found = False
    while _is_ms_declspec_start(parser):
        start = parser._advance()  # type: ignore
        parser._expect_punct("(")  # type: ignore
        depth = 1
        while depth > 0:
            token = parser._current()  # type: ignore
            if token.kind == TokenKind.EOF:
                raise make_error("Expected ')'", start)
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()  # type: ignore
        found = True
    return found


def _is_ms_declspec_start(parser: object) -> bool:
    token = parser._current()  # type: ignore
    return (
        token.kind == TokenKind.IDENT
        and token.lexeme == _MS_DECLSPEC_KEYWORD
        and parser._peek_punct("(")  # type: ignore
    )


def _skip_availability_attributes(
    parser: object,
    make_error: Callable[[str, Token], Exception],
) -> bool:
    found = False
    while _is_availability_attribute_start(parser):
        start = parser._advance()  # type: ignore
        parser._expect_punct("(")  # type: ignore
        depth = 1
        while depth > 0:
            token = parser._current()  # type: ignore
            if token.kind == TokenKind.EOF:
                raise make_error("Expected ')'", start)
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()  # type: ignore
        found = True
    return found


def _is_availability_attribute_start(parser: object) -> bool:
    token = parser._current()  # type: ignore
    if token.kind != TokenKind.IDENT or not isinstance(token.lexeme, str):
        return False
    name = token.lexeme
    return (
        (
            name in _AVAILABILITY_ATTRIBUTE_NAMES
            or any(name.endswith(suffix) for suffix in _AVAILABILITY_ATTRIBUTE_SUFFIXES)
        )
        and parser._peek_punct("(")  # type: ignore
    )


def _skip_calling_convention_identifiers(parser: object) -> bool:
    found = False
    while (
        parser._current().kind == TokenKind.IDENT  # type: ignore
        and parser._current().lexeme in _MS_CALLING_CONVENTION_IDENTIFIERS  # type: ignore
    ):
        parser._advance()  # type: ignore
        found = True
    return found


def _skip_calling_convention_identifiers_if(
    parser: object,
    predicate: Callable[[Token], bool],
) -> bool:
    token = parser._current()  # type: ignore
    if token.kind != TokenKind.IDENT or token.lexeme not in _MS_CALLING_CONVENTION_IDENTIFIERS:
        return False
    offset = 0
    while True:
        token = parser._peek(offset) if offset else parser._current()  # type: ignore
        if token.kind != TokenKind.IDENT or token.lexeme not in _MS_CALLING_CONVENTION_IDENTIFIERS:
            break
        offset += 1
    if not predicate(token):
        return False
    for _ in range(offset):
        parser._advance()  # type: ignore
    return True


def _skip_calling_convention_identifiers_before_pointer(parser: object) -> bool:
    return _skip_calling_convention_identifiers_if(
        parser,
        lambda token: token.kind == TokenKind.PUNCTUATOR and token.lexeme == "*",
    )


def _skip_calling_convention_identifiers_after_pointer(parser: object) -> bool:
    return _skip_calling_convention_identifiers_if(
        parser,
        lambda token: (
            token.kind == TokenKind.IDENT
            or (token.kind == TokenKind.PUNCTUATOR and token.lexeme in {"(", ")"})
        ),
    )


def _skip_type_name_attributes(parser: object, *, allow_gnu_attributes: bool) -> bool:
    found = False
    while True:
        skipped = _skip_ms_declspecs(
            parser,
            parser._make_error,  # type: ignore
        )
        if allow_gnu_attributes:
            skipped = (
                _skip_gnu_attributes(
                    parser,
                    parser._make_error,  # type: ignore
                )
                or skipped
            )
        if not skipped:
            return found
        found = True


def _skip_asm_label(
    parser: object,
    make_error: Callable[[str, Token], Exception] | None = None,
) -> bool:
    make_error = parser._make_error if make_error is None else make_error  # type: ignore
    token = parser._current()  # type: ignore
    if token.kind != TokenKind.IDENT or token.lexeme not in ("__asm__", "__asm", "asm"):
        return False
    start = parser._advance()  # type: ignore
    if not parser._check_punct("("):  # type: ignore
        return True
    parser._advance()  # type: ignore
    depth = 1
    while depth > 0:
        tok = parser._current()  # type: ignore
        if tok.kind == TokenKind.EOF:
            raise make_error("Expected ')'", start)
        if tok.kind == TokenKind.PUNCTUATOR:
            if tok.lexeme == "(":
                depth += 1
            elif tok.lexeme == ")":
                depth -= 1
        parser._advance()  # type: ignore
    return True
