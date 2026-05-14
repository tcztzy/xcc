from dataclasses import replace
from enum import Enum
from typing import cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BuiltinOffsetofExpr,
    CallExpr,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    ConditionalExpr,
    Expr,
    FloatLiteral,
    GenericExpr,
    Identifier,
    IntLiteral,
    LabelAddressExpr,
    MemberExpr,
    SizeofExpr,
    StatementExpr,
    StringLiteral,
    SubscriptExpr,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
)
from xcc.lexer import Token, TokenKind

from .type_specs import _GNU_EXTENSION_TYPES

FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
_EXTENSION_MARKER = "__extension__"
ALIGNOF_KEYWORDS = {"_Alignof", "__alignof__"}
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}
PAREN_TYPE_NAME_KEYWORDS = {
    "_Atomic",
    "_Bool",
    "_Complex",
    "__int128",
    "__uint128",
    "__int128_t",
    "__uint128_t",
    "__typeof__",
    "__typeof",
    "__typeof_unqual__",
    "__typeof_unqual",
    "_Float16",
    "__bf16",
    "__fp16",
    "_Float32",
    "_Float32x",
    "_Float64",
    "_Float64x",
    "_Float128",
    "char",
    "double",
    "enum",
    "float",
    "int",
    "long",
    "short",
    "signed",
    "struct",
    "typeof",
    "typeof_unqual",
    "union",
    "unsigned",
    "void",
}


def parse_expression(parser: object) -> Expr:
    expr = parser._parse_assignment()  # type: ignore[attr-defined]
    while parser._check_punct(","):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        right = parser._parse_assignment()  # type: ignore[attr-defined]
        expr = CommaExpr(expr, right)
    return expr


def parse_assignment(parser: object) -> Expr:
    expr = parser._parse_conditional()  # type: ignore[attr-defined]
    if parser._is_assignment_operator():  # type: ignore[attr-defined]
        op = str(parser._advance().lexeme)  # type: ignore[attr-defined]
        value = parser._parse_assignment()  # type: ignore[attr-defined]
        return AssignExpr(op, expr, value)
    return expr


def parse_conditional(parser: object) -> Expr:
    expr = parser._parse_logical_or()  # type: ignore[attr-defined]
    if not parser._check_punct("?"):  # type: ignore[attr-defined]
        return expr
    parser._advance()  # type: ignore[attr-defined]
    then_expr = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(":")  # type: ignore[attr-defined]
    else_expr = parser._parse_conditional()  # type: ignore[attr-defined]
    return ConditionalExpr(expr, then_expr, else_expr)


def parse_binary_left_associative(
    parser: object,
    operand_name: str,
    operators: tuple[str, ...],
) -> Expr:
    operand = getattr(parser, operand_name)
    expr = operand()
    while any(parser._check_punct(op) for op in operators):  # type: ignore[attr-defined]
        op = parser._advance().lexeme  # type: ignore[attr-defined]
        right = operand()
        expr = BinaryExpr(str(op), expr, right)
    return expr


def parse_logical_or(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_logical_and", ("||",))


def parse_logical_and(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_bitwise_or", ("&&",))


def parse_bitwise_or(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_bitwise_xor", ("|",))


def parse_bitwise_xor(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_bitwise_and", ("^",))


def parse_bitwise_and(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_equality", ("&",))


def parse_equality(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_relational", ("==", "!="))


def parse_relational(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_shift", ("<", "<=", ">", ">="))


def parse_shift(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_additive", ("<<", ">>"))


def parse_additive(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_multiplicative", ("+", "-"))


def parse_multiplicative(parser: object) -> Expr:
    return parse_binary_left_associative(parser, "_parse_unary", ("*", "/", "%"))


def parse_unary(parser: object) -> Expr:
    if parser._check_keyword(_EXTENSION_MARKER):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        return parser._parse_unary()  # type: ignore[attr-defined]
    if parser._check_keyword("sizeof"):  # type: ignore[attr-defined]
        return parser._parse_sizeof_expr()  # type: ignore[attr-defined]
    current = parser._current()  # type: ignore[attr-defined]
    if current.kind == TokenKind.KEYWORD and current.lexeme in ALIGNOF_KEYWORDS:
        return parser._parse_alignof_expr()  # type: ignore[attr-defined]
    if (
        parser._is_parenthesized_type_name_start()  # type: ignore[attr-defined]
        and not parser._looks_like_compound_literal()  # type: ignore[attr-defined]
    ):
        return parser._parse_cast_expr()  # type: ignore[attr-defined]
    if parser._check_punct("++") or parser._check_punct("--"):  # type: ignore[attr-defined]
        op = str(parser._advance().lexeme)  # type: ignore[attr-defined]
        operand = parser._parse_unary()  # type: ignore[attr-defined]
        return UpdateExpr(op, operand, False)
    if parser._check_punct("&&"):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        label = parser._expect(TokenKind.IDENT)  # type: ignore[attr-defined]
        assert isinstance(label.lexeme, str)
        return LabelAddressExpr(label.lexeme)
    if any(parser._check_punct(op) for op in ("+", "-", "!", "~", "&", "*")):  # type: ignore[attr-defined]
        op = parser._advance().lexeme  # type: ignore[attr-defined]
        operand = parser._parse_unary()  # type: ignore[attr-defined]
        return UnaryExpr(str(op), operand)
    return parser._parse_postfix()  # type: ignore[attr-defined]


def parse_sizeof_expr(parser: object) -> SizeofExpr:
    parser._advance()  # type: ignore[attr-defined]
    if parser._is_parenthesized_type_name_start():  # type: ignore[attr-defined]
        type_spec = parser._parse_parenthesized_type_name()  # type: ignore[attr-defined]
        return SizeofExpr(None, type_spec)
    operand = parser._parse_unary()  # type: ignore[attr-defined]
    return SizeofExpr(operand, None)


def parse_alignof_expr(parser: object) -> AlignofExpr:
    token = parser._advance()  # type: ignore[attr-defined]
    if parser._is_parenthesized_type_name_start():  # type: ignore[attr-defined]
        type_spec = parser._parse_parenthesized_type_name()  # type: ignore[attr-defined]
        return AlignofExpr(None, type_spec)
    if parser._std == "c11":  # type: ignore[attr-defined]
        raise parser._make_error("Invalid alignof operand", token)  # type: ignore[attr-defined]
    operand = parser._parse_unary()  # type: ignore[attr-defined]
    return AlignofExpr(operand, None)


def parse_typeof_type_spec(parser: object) -> TypeSpec:
    parser._expect_punct("(")  # type: ignore[attr-defined]
    if parser._try_parse_type_name():  # type: ignore[attr-defined]
        type_spec = parser._parse_type_name()  # type: ignore[attr-defined]
        parser._expect_punct(")")  # type: ignore[attr-defined]
        return type_spec
    expr = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    return TypeSpec("typeof", typeof_expr=expr)


def parse_cast_expr(parser: object) -> CastExpr:
    type_spec = parser._parse_parenthesized_type_name()  # type: ignore[attr-defined]
    operand = parser._parse_unary()  # type: ignore[attr-defined]
    return CastExpr(type_spec, operand)


def parse_parenthesized_type_name(parser: object) -> TypeSpec:
    parser._expect_punct("(")  # type: ignore[attr-defined]
    base_type = parser._parse_type_spec(context="type-name")  # type: ignore[attr-defined]
    name, declarator_ops = parser._parse_declarator(  # type: ignore[attr-defined]
        allow_abstract=True,
        allow_vla=True,
    )
    if name is not None:
        raise parser._make_error(  # type: ignore[attr-defined]
            f"Type name cannot declare identifier '{name}'",
            parser._current(),  # type: ignore[attr-defined]
        )
    parser._expect_punct(")")  # type: ignore[attr-defined]
    return parser._build_declarator_type(base_type, declarator_ops)  # type: ignore[attr-defined]


def is_parenthesized_type_name_start(parser: object) -> bool:
    if not parser._check_punct("("):  # type: ignore[attr-defined]
        return False
    index = parser._index + 1  # type: ignore[attr-defined]
    tokens = parser._tokens  # type: ignore[attr-defined]
    token = tokens[min(index, len(tokens) - 1)]
    while (token.kind == TokenKind.KEYWORD and token.lexeme in TYPE_QUALIFIER_KEYWORDS) or (
        token.kind == TokenKind.IDENT and token.lexeme in _IGNORED_IDENT_TYPE_QUALIFIERS
    ):
        index += 1
        token = tokens[min(index, len(tokens) - 1)]
    if token.kind == TokenKind.KEYWORD:
        return str(token.lexeme) in PAREN_TYPE_NAME_KEYWORDS
    if token.kind == TokenKind.IDENT and isinstance(token.lexeme, str):
        return (
            parser._is_typedef_name(token.lexeme)  # type: ignore[attr-defined]
            or token.lexeme in _GNU_EXTENSION_TYPES
        )
    return False


def parse_postfix(parser: object) -> Expr:
    if (
        parser._is_parenthesized_type_name_start()  # type: ignore[attr-defined]
        and parser._looks_like_compound_literal()  # type: ignore[attr-defined]
    ):
        expr = parser._parse_compound_literal_expr()  # type: ignore[attr-defined]
    else:
        expr = parser._parse_primary()  # type: ignore[attr-defined]
    while True:
        if parser._check_punct("("):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            args = parser._parse_arguments()  # type: ignore[attr-defined]
            parser._expect_punct(")")  # type: ignore[attr-defined]
            expr = CallExpr(expr, args)
            continue
        if parser._check_punct("["):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            index = parser._parse_expression()  # type: ignore[attr-defined]
            parser._expect_punct("]")  # type: ignore[attr-defined]
            expr = SubscriptExpr(expr, index)
            continue
        if parser._check_punct("."):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            member_token = parser._expect(TokenKind.IDENT)  # type: ignore[attr-defined]
            assert isinstance(member_token.lexeme, str)
            expr = MemberExpr(expr, member_token.lexeme, False)
            continue
        if parser._check_punct("->"):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            member_token = parser._expect(TokenKind.IDENT)  # type: ignore[attr-defined]
            assert isinstance(member_token.lexeme, str)
            expr = MemberExpr(expr, member_token.lexeme, True)
            continue
        if parser._check_punct("++") or parser._check_punct("--"):  # type: ignore[attr-defined]
            op = str(parser._advance().lexeme)  # type: ignore[attr-defined]
            expr = UpdateExpr(op, expr, True)
            continue
        break
    return expr


def looks_like_compound_literal(parser: object) -> bool:
    if not parser._is_parenthesized_type_name_start():  # type: ignore[attr-defined]
        return False
    saved_index = parser._index  # type: ignore[attr-defined]
    try:
        parser._parse_parenthesized_type_name()  # type: ignore[attr-defined]
        return parser._check_punct("{")  # type: ignore[attr-defined]
    except Exception as exc:
        if exc.__class__.__name__ != "ParserError":
            raise
        return False
    finally:
        parser._index = saved_index


def parse_compound_literal_expr(parser: object) -> CompoundLiteralExpr:
    type_spec = parser._parse_parenthesized_type_name()  # type: ignore[attr-defined]
    if not parser._check_punct("{"):  # type: ignore[attr-defined]
        raise parser._make_error("Expected '{'", parser._current())  # type: ignore[attr-defined]
    initializer = parser._parse_initializer_list()  # type: ignore[attr-defined]
    return CompoundLiteralExpr(type_spec, initializer)


def parse_arguments(parser: object) -> list[Expr]:
    if parser._check_punct(")"):  # type: ignore[attr-defined]
        return []
    args = [parser._parse_assignment()]  # type: ignore[attr-defined]
    while parser._check_punct(","):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        args.append(parser._parse_assignment())  # type: ignore[attr-defined]
    return args


def parse_primary(parser: object) -> Expr:
    token = parser._current()  # type: ignore[attr-defined]
    if token.kind == TokenKind.FLOAT_CONST:
        parser._advance()  # type: ignore[attr-defined]
        assert isinstance(token.lexeme, str)
        return FloatLiteral(token.lexeme)
    if token.kind == TokenKind.INT_CONST:
        parser._advance()  # type: ignore[attr-defined]
        assert isinstance(token.lexeme, str)
        return IntLiteral(token.lexeme)
    if token.kind == TokenKind.CHAR_CONST:
        parser._advance()  # type: ignore[attr-defined]
        assert isinstance(token.lexeme, str)
        return CharLiteral(token.lexeme)
    if parser._check_keyword("_Generic"):  # type: ignore[attr-defined]
        return parser._parse_generic_expr()  # type: ignore[attr-defined]
    if token.kind == TokenKind.STRING_LITERAL:
        return parser._parse_string_literal()  # type: ignore[attr-defined]
    if token.kind == TokenKind.IDENT and token.lexeme == "__builtin_offsetof":
        return parser._parse_builtin_offsetof()  # type: ignore[attr-defined]
    if token.kind == TokenKind.IDENT:
        parser._advance()  # type: ignore[attr-defined]
        assert isinstance(token.lexeme, str)
        return Identifier(token.lexeme)
    if parser._check_punct("("):  # type: ignore[attr-defined]
        if parser._peek_punct("{"):  # type: ignore[attr-defined]
            return parser._parse_statement_expr()  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        expr = parser._parse_expression()  # type: ignore[attr-defined]
        parser._expect_punct(")")  # type: ignore[attr-defined]
        return expr
    invalid_expression_starts = {
        "...",
        ")",
        "]",
        "}",
        ",",
        ":",
        "?",
        ";",
        "{",
        "##",
        "%:",
        "%:%:",
        "<:",
        ":>",
        "<%",
        "%>",
    }
    if token.kind == TokenKind.PUNCTUATOR and token.lexeme in invalid_expression_starts:
        raise parser._make_error(  # type: ignore[attr-defined]
            f"Expression cannot start with '{token.lexeme}': expected an operand",
            token,
        )
    if token.kind == TokenKind.KEYWORD:
        raise parser._make_error(  # type: ignore[attr-defined]
            f"Expression cannot start with keyword '{token.lexeme}': expected an operand",
            token,
        )
    if token.kind == TokenKind.EOF:
        raise parser._make_error("Expression is missing before end of input", token)  # type: ignore[attr-defined]
    if token.kind == TokenKind.PP_NUMBER:
        raise parser._make_error(  # type: ignore[attr-defined]
            f"Expression cannot start with preprocessing number: '{token.lexeme}'",
            token,
        )
    if token.kind == TokenKind.HEADER_NAME:
        raise parser._make_error(  # type: ignore[attr-defined]
            f"Expression cannot start with header name: '{token.lexeme}'",
            token,
        )
    kind_name = token.kind.name if isinstance(token.kind, Enum) else repr(token.kind)
    lexeme_hint = f" (lexeme {token.lexeme!r})" if token.lexeme is not None else ""
    raise parser._make_error(  # type: ignore[attr-defined]
        f"Expression cannot start with unsupported token kind '{kind_name}'{lexeme_hint}",
        token,
    )


def parse_builtin_offsetof(parser: object) -> BuiltinOffsetofExpr:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    type_spec = parser._parse_type_name()  # type: ignore[attr-defined]
    parser._expect_punct(",")  # type: ignore[attr-defined]
    token = parser._current()  # type: ignore[attr-defined]
    if token.kind != TokenKind.IDENT:
        raise parser._make_error("Expected member name in __builtin_offsetof", token)  # type: ignore[attr-defined]
    assert isinstance(token.lexeme, str)
    parts: list[str] = [token.lexeme]
    parser._advance()  # type: ignore[attr-defined]
    while parser._check_punct("."):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        token = parser._current()  # type: ignore[attr-defined]
        if token.kind != TokenKind.IDENT:
            raise parser._make_error(  # type: ignore[attr-defined]
                "Expected member name after '.' in __builtin_offsetof",
                token,
            )
        assert isinstance(token.lexeme, str)
        parts.append(token.lexeme)
        parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    return BuiltinOffsetofExpr(type_spec=type_spec, member=".".join(parts))


def parse_generic_expr(parser: object) -> GenericExpr:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    control = parser._parse_assignment()  # type: ignore[attr-defined]
    parser._expect_punct(",")  # type: ignore[attr-defined]
    associations: list[tuple[TypeSpec | None, Expr]] = []
    association_source_locations: list[tuple[int | None, int | None]] = []
    first_default_index: int | None = None
    first_default_token: Token | None = None
    association_index = 0
    parsed_type_positions: dict[tuple[object, ...], tuple[int, Token, str]] = {}
    while True:
        association_index += 1
        assoc_type: TypeSpec | None
        if parser._check_keyword("default"):  # type: ignore[attr-defined]
            default_token = parser._current()  # type: ignore[attr-defined]
            if first_default_index is not None:
                assert first_default_token is not None
                raise parser._make_error(
                    "Duplicate default generic association at position "
                    f"{association_index} (line {default_token.line}, column "
                    f"{default_token.column}): previous default was at position "
                    f"{first_default_index} (line {first_default_token.line}, "
                    f"column {first_default_token.column}); only one default "
                    "association is allowed",
                    parser._current(),
                )
            first_default_index = association_index
            first_default_token = default_token
            parser._advance()  # type: ignore[attr-defined]
            assoc_type = None
            association_source_locations.append((default_token.line, default_token.column))
        else:
            association_start_index = parser._index  # type: ignore[attr-defined]
            association_type_token = parser._current()  # type: ignore[attr-defined]
            assoc_type = replace(
                parser._parse_type_name(),  # type: ignore[attr-defined]
                source_line=association_type_token.line,
                source_column=association_type_token.column,
            )
            association_source_locations.append(
                (association_type_token.line, association_type_token.column)
            )
            association_end_index = parser._index  # type: ignore[attr-defined]
            association_type_spelling = parser._format_token_span(  # type: ignore[attr-defined]
                association_start_index,
                association_end_index,
            )
            if not parser._type_name_uses_typedef_alias(  # type: ignore[attr-defined]
                association_start_index,
                association_end_index,
            ):
                type_key = parser._generic_association_type_key(assoc_type)  # type: ignore[attr-defined]
                if type_key in parsed_type_positions:
                    previous_index, previous_token, previous_spelling = parsed_type_positions[
                        type_key
                    ]
                    relationship = "identical"
                    details = ""
                    if association_type_spelling != previous_spelling:
                        relationship = "canonical-equivalent"
                        details = (
                            f" (previous spelling: '{previous_spelling}'; "
                            f"current spelling: '{association_type_spelling}')"
                        )
                    raise parser._make_error(  # type: ignore[attr-defined]
                        "Duplicate generic type association at position "
                        f"{association_index} (line {association_type_token.line}, "
                        f"column {association_type_token.column}): previous "
                        f"{relationship} type association was at position "
                        f"{previous_index} (line {previous_token.line}, "
                        f"column {previous_token.column}){details}",
                        association_type_token,
                    )
                parsed_type_positions[type_key] = (
                    association_index,
                    association_type_token,
                    association_type_spelling,
                )
        parser._expect_punct(":")  # type: ignore[attr-defined]
        associations.append((assoc_type, parser._parse_assignment()))  # type: ignore[attr-defined]
        if not parser._check_punct(","):  # type: ignore[attr-defined]
            break
        parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    return GenericExpr(
        control,
        tuple(associations),
        tuple(association_source_locations),
    )


def parse_statement_expr(parser: object) -> StatementExpr:
    parser._expect_punct("(")  # type: ignore[attr-defined]
    body = parser._parse_compound_stmt()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    return StatementExpr(body)


def parse_string_literal(parser: object) -> StringLiteral:
    token = parser._expect(TokenKind.STRING_LITERAL)  # type: ignore[attr-defined]
    assert isinstance(token.lexeme, str)
    prefix, body = split_string_literal(parser, token.lexeme, token)
    while parser._current().kind == TokenKind.STRING_LITERAL:  # type: ignore[attr-defined]
        token = parser._advance()  # type: ignore[attr-defined]
        assert isinstance(token.lexeme, str)
        next_prefix, next_body = split_string_literal(parser, token.lexeme, token)
        prefix = merge_string_prefix(parser, prefix, next_prefix, token)
        body += next_body
    return StringLiteral(f'{prefix}"{body}"')


def split_string_literal(parser: object, lexeme: str, token: Token) -> tuple[str, str]:
    if lexeme.startswith('"') and lexeme.endswith('"'):
        return "", lexeme[1:-1]
    if lexeme.startswith('u8"') and lexeme.endswith('"'):
        return "u8", lexeme[3:-1]
    if (
        len(lexeme) >= 3
        and lexeme[0] in {"u", "U", "L"}
        and lexeme[1] == '"'
        and lexeme.endswith('"')
    ):
        return lexeme[0], lexeme[2:-1]
    raise parser._make_error("Invalid string literal", token)  # type: ignore[attr-defined]


def merge_string_prefix(
    parser: object,
    prefix: str,
    next_prefix: str,
    token: Token,
) -> str:
    if prefix == next_prefix or not next_prefix:
        return prefix
    if not prefix:
        return next_prefix
    raise parser._make_error("Incompatible string literal prefixes", token)  # type: ignore[attr-defined]


def format_token_span(parser: object, start: int, end: int) -> str:
    return " ".join(
        str(token.lexeme)
        for token in parser._tokens[start:end]  # type: ignore[attr-defined]
        if token.lexeme is not None
    )


def type_name_uses_typedef_alias(parser: object, start: int, end: int) -> bool:
    for token in parser._tokens[start:end]:  # type: ignore[attr-defined]
        if (
            token.kind == TokenKind.IDENT
            and isinstance(token.lexeme, str)
            and parser._is_typedef_name(token.lexeme)  # type: ignore[attr-defined]
        ):
            return True
    return False


def generic_association_type_key(parser: object, type_spec: TypeSpec) -> tuple[object, ...]:
    def stable(value: object) -> object:
        try:
            hash(value)
        except TypeError:
            return repr(value)
        return value

    def op_key(op: DeclaratorOp) -> tuple[object, ...]:
        kind, value = op
        if kind == "arr" and isinstance(value, ArrayDecl):
            return (
                kind,
                stable(value.length),
                tuple(sorted(value.qualifiers)),
                value.has_static_bound,
            )
        if kind == "func" and isinstance(value, tuple):
            params, is_variadic = cast(FunctionDeclarator, value)
            if params is None:
                param_keys = None
            else:
                param_keys = tuple(generic_association_type_key(parser, param) for param in params)
            return (kind, param_keys, is_variadic)
        return (kind, stable(value))

    return (
        type_spec.name,
        tuple(sorted(type_spec.qualifiers)),
        type_spec.is_atomic,
        None
        if type_spec.atomic_target is None
        else generic_association_type_key(parser, type_spec.atomic_target),
        type_spec.enum_tag,
        tuple((name, stable(expr)) for name, expr in type_spec.enum_members),
        type_spec.record_tag,
        tuple(
            (
                generic_association_type_key(parser, member.type_spec),
                member.name,
                member.alignment,
                stable(member.bit_width_expr),
            )
            for member in type_spec.record_members
        ),
        tuple(op_key(op) for op in type_spec.declarator_ops),
    )
