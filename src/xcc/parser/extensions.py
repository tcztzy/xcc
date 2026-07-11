from typing import TYPE_CHECKING

from xcc.lexer import Token, TokenKind

if TYPE_CHECKING:
    from . import Parser

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


def _skip_extension_markers(parser: "Parser") -> None:
    while parser._check_keyword(_EXTENSION_MARKER):
        parser._advance()


def _consume_overloadable_decl_attributes(parser: "Parser") -> bool:
    _, has_overloadable = _consume_decl_attributes(parser)
    return has_overloadable


def _skip_decl_attributes(parser: "Parser") -> bool:
    found, _ = _consume_decl_attributes(parser)
    return found


def _skip_gnu_attributes(parser: "Parser") -> bool:
    found, _ = _consume_gnu_attributes(parser)
    return found


def _skip_decl_extensions(parser: "Parser") -> None:
    _consume_decl_extensions(parser)


def _consume_decl_extensions(parser: "Parser") -> tuple[bool, bool]:
    found = False
    has_transparent_union = False
    while True:
        (
            attr_found,
            _attr_has_overloadable,
            _alignment,
            _alignment_token,
            attr_has_transparent_union,
        ) = _consume_decl_attributes_with_details(parser)
        asm_found = _skip_asm_label(parser)
        if not attr_found and not asm_found:
            break
        found = True
        has_transparent_union = has_transparent_union or attr_has_transparent_union
    return found, has_transparent_union


def _consume_decl_attributes(parser: "Parser") -> tuple[bool, bool]:
    found, has_overloadable, _, _ = _consume_decl_attributes_with_alignment(parser)
    return found, has_overloadable


def _consume_decl_attribute_alignment(parser: "Parser") -> tuple[bool, int | None, Token | None]:
    found, _, alignment, alignment_token = _consume_decl_attributes_with_alignment(parser)
    return found, alignment, alignment_token


def _consume_decl_attributes_with_alignment(
    parser: "Parser",
) -> tuple[bool, bool, int | None, Token | None]:
    (
        found,
        has_overloadable,
        alignment,
        alignment_token,
        _has_transparent_union,
    ) = _consume_decl_attributes_with_details(parser)
    return found, has_overloadable, alignment, alignment_token


def _consume_decl_attributes_with_details(
    parser: "Parser",
) -> tuple[bool, bool, int | None, Token | None, bool]:
    found = False
    has_overloadable = False
    has_transparent_union = False
    alignment: int | None = None
    alignment_token: Token | None = None
    while True:
        (
            gnu_found,
            gnu_has_overloadable,
            gnu_alignment,
            gnu_alignment_token,
            gnu_has_transparent_union,
        ) = _consume_gnu_attributes_with_details(parser)
        ms_found = _skip_ms_declspecs(parser)
        availability_found = _skip_availability_attributes(parser)
        found = found or gnu_found or ms_found or availability_found
        has_overloadable = has_overloadable or gnu_has_overloadable
        has_transparent_union = has_transparent_union or gnu_has_transparent_union
        if gnu_alignment is not None:
            current_alignment: int = 0
            if alignment is not None:
                current_alignment = alignment
            if alignment is None or gnu_alignment > current_alignment:
                alignment = gnu_alignment
                alignment_token = gnu_alignment_token
        if not gnu_found and not ms_found and not availability_found:
            break
    return found, has_overloadable, alignment, alignment_token, has_transparent_union


def _consume_gnu_attributes(parser: "Parser") -> tuple[bool, bool]:
    found, has_overloadable, _, _ = _consume_gnu_attributes_with_alignment(parser)
    return found, has_overloadable


def _consume_gnu_attributes_with_alignment(
    parser: "Parser",
) -> tuple[bool, bool, int | None, Token | None]:
    (
        found,
        has_overloadable,
        alignment,
        alignment_token,
        _has_transparent_union,
    ) = _consume_gnu_attributes_with_details(parser)
    return found, has_overloadable, alignment, alignment_token


def _consume_gnu_attributes_with_details(
    parser: "Parser",
) -> tuple[bool, bool, int | None, Token | None, bool]:
    found = False
    has_overloadable = False
    has_transparent_union = False
    alignment: int | None = None
    alignment_token: Token | None = None
    while _is_gnu_attribute_start(parser):
        start = parser._advance()
        parser._expect_punct("(")
        parser._expect_punct("(")
        depth = 2
        while depth > 0:
            token = parser._current()
            if token.kind == TokenKind.EOF:
                raise parser._make_error("Expected ')'", start)
            if token.kind == TokenKind.IDENT and token.lexeme == "overloadable":
                has_overloadable = True
            if token.kind == TokenKind.IDENT and token.lexeme in {
                "transparent_union",
                "__transparent_union__",
            }:
                has_transparent_union = True
            if (
                depth == 2
                and token.kind == TokenKind.IDENT
                and token.lexeme in {"aligned", "__aligned__"}
                and parser._peek_punct("(")
            ):
                attr_token = token
                parser._advance()
                parser._expect_punct("(")
                if parser._check_punct(")"):
                    parser._advance()
                    found = True
                    continue
                expr = parser._parse_conditional()
                parsed_alignment = parser._eval_array_size_expr(expr)
                if parsed_alignment is None:
                    raise parser._make_error(
                        "Invalid alignment attribute: argument must be an "
                        "integer constant expression",
                        attr_token,
                    )
                if parsed_alignment <= 0:
                    raise parser._make_error(
                        "Invalid alignment attribute: argument must be positive",
                        attr_token,
                    )
                if (parsed_alignment & (parsed_alignment - 1)) != 0:
                    raise parser._make_error(
                        "Invalid alignment attribute: argument must evaluate to a power of two",
                        attr_token,
                    )
                current_alignment: int = 0
                if alignment is not None:
                    current_alignment = alignment
                if alignment is None or parsed_alignment > current_alignment:
                    alignment = parsed_alignment
                    alignment_token = attr_token
                parser._expect_punct(")")
                found = True
                continue
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()
        found = True
    return found, has_overloadable, alignment, alignment_token, has_transparent_union


def _is_gnu_attribute_start(parser: "Parser") -> bool:
    token = parser._current()
    if token.kind != TokenKind.IDENT or token.lexeme != "__attribute__":
        return False
    first = parser._peek(1)
    second = parser._peek(2)
    return (
        first.kind == TokenKind.PUNCTUATOR
        and first.lexeme == "("
        and second.kind == TokenKind.PUNCTUATOR
        and second.lexeme == "("
    )


def _skip_ms_declspecs(parser: "Parser") -> bool:
    found = False
    while _is_ms_declspec_start(parser):
        start = parser._advance()
        parser._expect_punct("(")
        depth = 1
        while depth > 0:
            token = parser._current()
            if token.kind == TokenKind.EOF:
                raise parser._make_error("Expected ')'", start)
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()
        found = True
    return found


def _is_ms_declspec_start(parser: "Parser") -> bool:
    token = parser._current()
    return (
        token.kind == TokenKind.IDENT
        and token.lexeme == _MS_DECLSPEC_KEYWORD
        and parser._peek_punct("(")
    )


def _skip_availability_attributes(parser: "Parser") -> bool:
    found = False
    while _is_availability_attribute_start(parser):
        start = parser._advance()
        parser._expect_punct("(")
        depth = 1
        while depth > 0:
            token = parser._current()
            if token.kind == TokenKind.EOF:
                raise parser._make_error("Expected ')'", start)
            if token.kind == TokenKind.PUNCTUATOR:
                if token.lexeme == "(":
                    depth += 1
                elif token.lexeme == ")":
                    depth -= 1
            parser._advance()
        found = True
    return found


def _is_availability_attribute_start(parser: "Parser") -> bool:
    token = parser._current()
    if token.kind != TokenKind.IDENT or not isinstance(token.lexeme, str):
        return False
    name = token.lexeme
    has_availability_suffix = False
    for suffix in _AVAILABILITY_ATTRIBUTE_SUFFIXES:
        if name.endswith(suffix):
            has_availability_suffix = True
            break
    return (
        name in _AVAILABILITY_ATTRIBUTE_NAMES or has_availability_suffix
    ) and parser._peek_punct("(")


def _skip_calling_convention_identifiers(parser: "Parser") -> bool:
    found = False
    while (
        parser._current().kind == TokenKind.IDENT
        and parser._current().lexeme in _MS_CALLING_CONVENTION_IDENTIFIERS
    ):
        parser._advance()
        found = True
    return found


def _skip_calling_convention_identifiers_for_pointer_context(
    parser: "Parser",
    after_pointer: bool,
) -> bool:
    token = parser._current()
    if token.kind != TokenKind.IDENT or token.lexeme not in _MS_CALLING_CONVENTION_IDENTIFIERS:
        return False
    offset = 0
    while True:
        token = parser._peek(offset) if offset else parser._current()
        if token.kind != TokenKind.IDENT or token.lexeme not in _MS_CALLING_CONVENTION_IDENTIFIERS:
            break
        offset += 1
    is_expected_token = (
        _is_pointer_suffix_token(token) if after_pointer else _is_pointer_token(token)
    )
    if not is_expected_token:
        return False
    for _ in range(offset):
        parser._advance()
    return True


def _skip_calling_convention_identifiers_before_pointer(parser: "Parser") -> bool:
    return _skip_calling_convention_identifiers_for_pointer_context(parser, False)


def _skip_calling_convention_identifiers_after_pointer(parser: "Parser") -> bool:
    return _skip_calling_convention_identifiers_for_pointer_context(parser, True)


def _is_pointer_token(token: Token) -> bool:
    return token.kind == TokenKind.PUNCTUATOR and token.lexeme == "*"


def _is_pointer_suffix_token(token: Token) -> bool:
    return token.kind == TokenKind.IDENT or (
        token.kind == TokenKind.PUNCTUATOR and token.lexeme in {"(", ")"}
    )


def _skip_type_name_attributes(parser: "Parser", *, allow_gnu_attributes: bool) -> bool:
    found = False
    while True:
        skipped = _skip_ms_declspecs(parser)
        if allow_gnu_attributes:
            skipped = _skip_gnu_attributes(parser) or skipped
        if not skipped:
            return found
        found = True


def _skip_asm_label(parser: "Parser") -> bool:
    token = parser._current()
    if token.kind != TokenKind.IDENT or token.lexeme not in ("__asm__", "__asm", "asm"):
        return False
    start = parser._advance()
    if not parser._check_punct("("):
        return True
    parser._advance()
    depth = 1
    while depth > 0:
        tok = parser._current()
        if tok.kind == TokenKind.EOF:
            raise parser._make_error("Expected ')'", start)
        if tok.kind == TokenKind.PUNCTUATOR:
            if tok.lexeme == "(":
                depth += 1
            elif tok.lexeme == ")":
                depth -= 1
        parser._advance()
    return True
