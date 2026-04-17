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
_EXTENSION_MARKER = "__extension__"


def _skip_extension_markers(parser: object) -> None:
    while parser._check_keyword(_EXTENSION_MARKER):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]


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
    found = False
    has_overloadable = False
    while True:
        gnu_found, gnu_has_overloadable = _consume_gnu_attributes(
            parser,
            parser._make_error,  # type: ignore[attr-defined]
        )
        ms_found = _skip_ms_declspecs(
            parser,
            parser._make_error,  # type: ignore[attr-defined]
        )
        found = found or gnu_found or ms_found
        has_overloadable = has_overloadable or gnu_has_overloadable
        if not gnu_found and not ms_found:
            break
    return found, has_overloadable


def _consume_gnu_attributes(
    parser: object,
    make_error: Callable[[str, Token], Exception],
) -> tuple[bool, bool]:
    found = False
    has_overloadable = False
    while _is_gnu_attribute_start(parser):
        start = parser._advance()  # type: ignore[attr-defined]
        parser._expect_punct("(")  # type: ignore[attr-defined]
        parser._expect_punct("(")  # type: ignore[attr-defined]
        depth = 2
        while depth > 0:
            token = parser._current()  # type: ignore[attr-defined]
            if token.kind == TokenKind.EOF:
                raise make_error("Expected ')'", start)
            if token.kind == TokenKind.IDENT and token.lexeme == "overloadable":
                has_overloadable = True
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()  # type: ignore[attr-defined]
        found = True
    return found, has_overloadable


def _is_gnu_attribute_start(parser: object) -> bool:
    token = parser._current()  # type: ignore[attr-defined]
    if token.kind != TokenKind.IDENT or token.lexeme != "__attribute__":
        return False
    first = parser._peek(1)  # type: ignore[attr-defined]
    second = parser._peek(2)  # type: ignore[attr-defined]
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
        start = parser._advance()  # type: ignore[attr-defined]
        parser._expect_punct("(")  # type: ignore[attr-defined]
        depth = 1
        while depth > 0:
            token = parser._current()  # type: ignore[attr-defined]
            if token.kind == TokenKind.EOF:
                raise make_error("Expected ')'", start)
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()  # type: ignore[attr-defined]
        found = True
    return found


def _is_ms_declspec_start(parser: object) -> bool:
    token = parser._current()  # type: ignore[attr-defined]
    return (
        token.kind == TokenKind.IDENT
        and token.lexeme == _MS_DECLSPEC_KEYWORD
        and parser._peek_punct("(")  # type: ignore[attr-defined]
    )


def _skip_calling_convention_identifiers(parser: object) -> bool:
    found = False
    while (
        parser._current().kind == TokenKind.IDENT  # type: ignore[attr-defined]
        and parser._current().lexeme in _MS_CALLING_CONVENTION_IDENTIFIERS  # type: ignore[attr-defined]
    ):
        parser._advance()  # type: ignore[attr-defined]
        found = True
    return found


def _skip_calling_convention_identifiers_if(
    parser: object,
    predicate: Callable[[Token], bool],
) -> bool:
    token = parser._current()  # type: ignore[attr-defined]
    if token.kind != TokenKind.IDENT or token.lexeme not in _MS_CALLING_CONVENTION_IDENTIFIERS:
        return False
    offset = 0
    while True:
        token = parser._peek(offset) if offset else parser._current()  # type: ignore[attr-defined]
        if token.kind != TokenKind.IDENT or token.lexeme not in _MS_CALLING_CONVENTION_IDENTIFIERS:
            break
        offset += 1
    if not predicate(token):
        return False
    for _ in range(offset):
        parser._advance()  # type: ignore[attr-defined]
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
            parser._make_error,  # type: ignore[attr-defined]
        )
        if allow_gnu_attributes:
            skipped = (
                _skip_gnu_attributes(
                    parser,
                    parser._make_error,  # type: ignore[attr-defined]
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
    make_error = parser._make_error if make_error is None else make_error  # type: ignore[attr-defined]
    token = parser._current()  # type: ignore[attr-defined]
    if token.kind != TokenKind.IDENT or token.lexeme not in ("__asm__", "__asm", "asm"):
        return False
    start = parser._advance()  # type: ignore[attr-defined]
    if not parser._check_punct("("):  # type: ignore[attr-defined]
        return True
    parser._advance()  # type: ignore[attr-defined]
    depth = 1
    while depth > 0:
        tok = parser._current()  # type: ignore[attr-defined]
        if tok.kind == TokenKind.EOF:
            raise make_error("Expected ')'", start)
        if tok.kind == TokenKind.PUNCTUATOR:
            if tok.lexeme == "(":
                depth += 1
            elif tok.lexeme == ")":
                depth -= 1
        parser._advance()  # type: ignore[attr-defined]
    return True
