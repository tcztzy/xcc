from typing import TYPE_CHECKING, cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BuiltinOffsetofExpr,
    BuiltinTypesCompatExpr,
    BuiltinVaArgExpr,
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

from .type_specs import _GNU_EXTENSION_TYPES, ParserError

if TYPE_CHECKING:
    from . import Parser

FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
_EXTENSION_MARKER = "__extension__"
ALIGNOF_KEYWORDS = {"_Alignof", "__alignof__"}
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict", "__restrict", "__restrict__"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}
_CANONICAL_TYPE_QUALIFIER_ORDER = ("const", "restrict", "volatile", "_Atomic")
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


def parse_expression(parser: "Parser") -> Expr:
    expr = parser._parse_assignment()
    while parser._check_punct(","):
        parser._advance()
        right = parser._parse_assignment()
        expr = CommaExpr(expr, right)
    return expr


def parse_assignment(parser: "Parser") -> Expr:
    expr = parser._parse_conditional()
    if parser._is_assignment_operator():
        op = str(parser._advance().lexeme)
        value = parser._parse_assignment()
        return AssignExpr(op, expr, value)
    return expr


def parse_conditional(parser: "Parser") -> Expr:
    expr = parser._parse_logical_or()
    if not parser._check_punct("?"):
        return expr
    parser._advance()
    then_expr = parser._parse_expression()
    parser._expect_punct(":")
    else_expr = parser._parse_conditional()
    return ConditionalExpr(expr, then_expr, else_expr)


def parse_binary_left_associative(
    parser: "Parser",
    operand_name: str,
    _operators: tuple[str, ...],
) -> Expr:
    expr = _parse_binary_operand(parser, operand_name)
    while _check_binary_operator(parser, operand_name):
        op = parser._advance().lexeme
        right = _parse_binary_operand(parser, operand_name)
        expr = BinaryExpr(str(op), expr, right)
    return expr


def _check_binary_operator(parser: "Parser", operand_name: str) -> bool:
    if operand_name == "_parse_logical_and":
        return parser._check_punct("||")
    if operand_name == "_parse_bitwise_or":
        return parser._check_punct("&&")
    if operand_name == "_parse_bitwise_xor":
        return parser._check_punct("|")
    if operand_name == "_parse_bitwise_and":
        return parser._check_punct("^")
    if operand_name == "_parse_equality":
        return parser._check_punct("&")
    if operand_name == "_parse_relational":
        if parser._check_punct("=="):
            return True
        return parser._check_punct("!=")
    if operand_name == "_parse_shift":
        if parser._check_punct("<"):
            return True
        if parser._check_punct("<="):
            return True
        if parser._check_punct(">"):
            return True
        return parser._check_punct(">=")
    if operand_name == "_parse_additive":
        if parser._check_punct("<<"):
            return True
        return parser._check_punct(">>")
    if operand_name == "_parse_multiplicative":
        if parser._check_punct("+"):
            return True
        return parser._check_punct("-")
    if operand_name == "_parse_unary":
        if parser._check_punct("*"):
            return True
        if parser._check_punct("/"):
            return True
        return parser._check_punct("%")
    raise AssertionError(f"unhandled binary operator parser: {operand_name}")  # pragma: no cover


def _parse_binary_operand(parser: "Parser", operand_name: str) -> Expr:
    if operand_name == "_parse_logical_and":
        return parser._parse_logical_and()
    if operand_name == "_parse_bitwise_or":
        return parser._parse_bitwise_or()
    if operand_name == "_parse_bitwise_xor":
        return parser._parse_bitwise_xor()
    if operand_name == "_parse_bitwise_and":
        return parser._parse_bitwise_and()
    if operand_name == "_parse_equality":
        return parser._parse_equality()
    if operand_name == "_parse_relational":
        return parser._parse_relational()
    if operand_name == "_parse_shift":
        return parser._parse_shift()
    if operand_name == "_parse_additive":
        return parser._parse_additive()
    if operand_name == "_parse_multiplicative":
        return parser._parse_multiplicative()
    if operand_name == "_parse_unary":
        return parser._parse_unary()
    raise AssertionError(f"unhandled binary operand parser: {operand_name}")  # pragma: no cover


def parse_logical_or(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_logical_and", ("||",))


def parse_logical_and(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_bitwise_or", ("&&",))


def parse_bitwise_or(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_bitwise_xor", ("|",))


def parse_bitwise_xor(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_bitwise_and", ("^",))


def parse_bitwise_and(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_equality", ("&",))


def parse_equality(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_relational", ("==", "!="))


def parse_relational(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_shift", ("<", "<=", ">", ">="))


def parse_shift(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_additive", ("<<", ">>"))


def parse_additive(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_multiplicative", ("+", "-"))


def parse_multiplicative(parser: "Parser") -> Expr:
    return parse_binary_left_associative(parser, "_parse_unary", ("*", "/", "%"))


def parse_unary(parser: "Parser") -> Expr:
    if parser._check_keyword(_EXTENSION_MARKER):
        parser._advance()
        return parser._parse_unary()
    if parser._check_keyword("sizeof"):
        return parser._parse_sizeof_expr()
    current = parser._current()
    if current.kind == TokenKind.KEYWORD and current.lexeme in ALIGNOF_KEYWORDS:
        return parser._parse_alignof_expr()
    if parser._is_parenthesized_type_name_start() and not parser._looks_like_compound_literal():
        return parser._parse_cast_expr()
    if parser._check_punct("++") or parser._check_punct("--"):
        op = str(parser._advance().lexeme)
        operand = parser._parse_unary()
        return UpdateExpr(op, operand, False)
    if parser._check_punct("&&"):
        parser._advance()
        label = parser._expect(TokenKind.IDENT)
        assert isinstance(label.lexeme, str)
        return LabelAddressExpr(label.lexeme)
    if _check_unary_operator(parser):
        op = str(parser._advance().lexeme)
        operand = parser._parse_unary()
        return UnaryExpr(op, operand)
    return parser._parse_postfix()


def _check_unary_operator(parser: "Parser") -> bool:
    if parser._check_punct("+"):
        return True
    if parser._check_punct("-"):
        return True
    if parser._check_punct("!"):
        return True
    if parser._check_punct("~"):
        return True
    if parser._check_punct("&"):
        return True
    return parser._check_punct("*")


def parse_sizeof_expr(parser: "Parser") -> SizeofExpr:
    parser._advance()
    if parser._is_parenthesized_type_name_start():
        type_spec = parser._parse_parenthesized_type_name()
        return SizeofExpr(None, type_spec)
    operand = parser._parse_unary()
    return SizeofExpr(operand, None)


def parse_alignof_expr(parser: "Parser") -> AlignofExpr:
    token = parser._advance()
    is_gnu = token.lexeme == "__alignof__"
    if parser._is_parenthesized_type_name_start():
        type_spec = parser._parse_parenthesized_type_name()
        return AlignofExpr(None, type_spec, is_gnu)
    if parser._std == "c11" and not is_gnu:
        raise parser._make_error("Invalid alignof operand", token)
    operand = parser._parse_unary()
    return AlignofExpr(operand, None, is_gnu)


def parse_typeof_type_spec(parser: "Parser") -> TypeSpec:
    parser._expect_punct("(")
    if parser._try_parse_type_name():
        type_spec = parser._parse_type_name()
        parser._expect_punct(")")
        return type_spec
    expr = parser._parse_expression()
    parser._expect_punct(")")
    return TypeSpec("typeof", typeof_expr=expr)


def parse_cast_expr(parser: "Parser") -> CastExpr:
    type_spec = parser._parse_parenthesized_type_name()
    operand = parser._parse_unary()
    return CastExpr(type_spec, operand)


def _with_type_spec_source(type_spec: TypeSpec, line: int, column: int) -> TypeSpec:
    return TypeSpec(
        type_spec.name,
        type_spec.pointer_depth,
        type_spec.array_lengths,
        type_spec.declarator_ops,
        type_spec.qualifiers,
        type_spec.is_atomic,
        type_spec.atomic_target,
        type_spec.enum_tag,
        type_spec.enum_members,
        type_spec.record_tag,
        type_spec.record_members,
        type_spec.has_record_body,
        line,
        column,
        type_spec.typeof_expr,
    )


def parse_parenthesized_type_name(parser: "Parser") -> TypeSpec:
    parser._expect_punct("(")
    base_type = parser._parse_type_spec(context="type-name")
    name, declarator_ops = parser._parse_declarator(
        allow_abstract=True,
        allow_vla=True,
    )
    if name is not None:
        raise parser._make_error(
            f"Type name cannot declare identifier '{name}'",
            parser._current(),
        )
    parser._expect_punct(")")
    return parser._build_declarator_type(base_type, declarator_ops)


def is_parenthesized_type_name_start(parser: "Parser") -> bool:
    if not parser._check_punct("("):
        return False
    index = parser._index + 1
    tokens = parser._tokens
    token = tokens[min(index, len(tokens) - 1)]
    while (token.kind == TokenKind.KEYWORD and token.lexeme in TYPE_QUALIFIER_KEYWORDS) or (
        token.kind == TokenKind.IDENT and token.lexeme in _IGNORED_IDENT_TYPE_QUALIFIERS
    ):
        index += 1
        token = tokens[min(index, len(tokens) - 1)]
    if token.kind == TokenKind.KEYWORD:
        return str(token.lexeme) in PAREN_TYPE_NAME_KEYWORDS
    if token.kind == TokenKind.IDENT and isinstance(token.lexeme, str):
        return parser._is_typedef_name(token.lexeme) or token.lexeme in _GNU_EXTENSION_TYPES
    return False


def parse_postfix(parser: "Parser") -> Expr:
    expr: Expr
    if parser._is_parenthesized_type_name_start():
        # Cast expressions are intercepted by parse_unary; only
        # compound literals survive to this point.
        expr = parser._parse_compound_literal_expr()
    else:
        expr = parser._parse_primary()
    while True:
        if parser._check_punct("("):
            parser._advance()
            # __builtin_va_arg(ap, type) takes a type name as 2nd argument
            if isinstance(expr, Identifier) and expr.name == "__builtin_va_arg":
                ap = parser._parse_assignment()
                parser._expect_punct(",")
                va_arg_type_spec = parser._parse_type_name()
                parser._expect_punct(")")
                expr = BuiltinVaArgExpr(ap=ap, type_spec=va_arg_type_spec)
            elif isinstance(expr, Identifier) and expr.name in {
                "_Py_CAST",
                "_Py_STATIC_CAST",
                "_Py_FUNC_CAST",
            }:
                cast_type_spec = parser._parse_type_name()
                parser._expect_punct(",")
                value = parser._parse_assignment()
                parser._expect_punct(")")
                expr = CastExpr(cast_type_spec, value)
            else:
                args = parser._parse_arguments()
                parser._expect_punct(")")
                expr = CallExpr(expr, args)
            continue
        if parser._check_punct("["):
            parser._advance()
            index = parser._parse_expression()
            parser._expect_punct("]")
            expr = SubscriptExpr(expr, index)
            continue
        if parser._check_punct("."):
            parser._advance()
            member_token = parser._expect(TokenKind.IDENT)
            assert isinstance(member_token.lexeme, str)
            expr = MemberExpr(expr, member_token.lexeme, False)
            continue
        if parser._check_punct("->"):
            parser._advance()
            member_token = parser._expect(TokenKind.IDENT)
            assert isinstance(member_token.lexeme, str)
            expr = MemberExpr(expr, member_token.lexeme, True)
            continue
        if parser._check_punct("++") or parser._check_punct("--"):
            op = str(parser._advance().lexeme)
            expr = UpdateExpr(op, expr, True)
            continue
        break
    return expr


def looks_like_compound_literal(parser: "Parser") -> bool:
    if not parser._is_parenthesized_type_name_start():
        return False
    saved_index = parser._index
    result = False
    try:
        parser._parse_parenthesized_type_name()
        result = parser._check_punct("{")
    except ParserError:
        result = False
    parser._index = saved_index
    return result


def parse_compound_literal_expr(parser: "Parser") -> CompoundLiteralExpr:
    type_spec = parser._parse_parenthesized_type_name()
    if not parser._check_punct("{"):
        raise parser._make_error("Expected '{'", parser._current())
    initializer = parser._parse_initializer_list()
    return CompoundLiteralExpr(type_spec, initializer)


def parse_arguments(parser: "Parser") -> list[Expr]:
    if parser._check_punct(")"):
        return []
    args = [parser._parse_assignment()]
    while parser._check_punct(","):
        parser._advance()
        args.append(parser._parse_assignment())
    return args


def parse_primary(parser: "Parser") -> Expr:
    token = parser._current()
    if token.kind == TokenKind.FLOAT_CONST:
        parser._advance()
        assert isinstance(token.lexeme, str)
        return FloatLiteral(token.lexeme)
    if token.kind == TokenKind.INT_CONST:
        parser._advance()
        assert isinstance(token.lexeme, str)
        return IntLiteral(token.lexeme)
    if token.kind == TokenKind.CHAR_CONST:
        parser._advance()
        assert isinstance(token.lexeme, str)
        return CharLiteral(token.lexeme)
    if parser._check_keyword("_Generic"):
        return parser._parse_generic_expr()
    if token.kind == TokenKind.STRING_LITERAL:
        return parser._parse_string_literal()
    if token.kind == TokenKind.IDENT and token.lexeme == "__builtin_offsetof":
        return parser._parse_builtin_offsetof()
    if token.kind == TokenKind.IDENT and token.lexeme == "__builtin_types_compatible_p":
        return parser._parse_builtin_types_compatible_p()
    if token.kind == TokenKind.IDENT:
        parser._advance()
        assert isinstance(token.lexeme, str)
        return Identifier(token.lexeme)
    if parser._check_punct("("):
        if parser._peek_punct("{"):
            return parser._parse_statement_expr()
        parser._advance()
        expr = parser._parse_expression()
        parser._expect_punct(")")
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
        raise parser._make_error(
            f"Expression cannot start with '{token.lexeme}': expected an operand",
            token,
        )
    if token.kind == TokenKind.KEYWORD:
        raise parser._make_error(
            f"Expression cannot start with keyword '{token.lexeme}': expected an operand",
            token,
        )
    if token.kind == TokenKind.EOF:
        raise parser._make_error("Expression is missing before end of input", token)
    if token.kind == TokenKind.PP_NUMBER:
        raise parser._make_error(
            f"Expression cannot start with preprocessing number: '{token.lexeme}'",
            token,
        )
    if token.kind == TokenKind.HEADER_NAME:
        raise parser._make_error(
            f"Expression cannot start with header name: '{token.lexeme}'",
            token,
        )
    lexeme_hint = f" (lexeme '{token.lexeme}')" if token.lexeme is not None else ""
    raise parser._make_error(
        f"Expression cannot start with unsupported token kind{lexeme_hint}",
        token,
    )


def parse_builtin_offsetof(parser: "Parser") -> BuiltinOffsetofExpr:
    parser._advance()
    parser._expect_punct("(")
    type_spec = parser._parse_type_name()
    parser._expect_punct(",")
    token = parser._current()
    if token.kind != TokenKind.IDENT:
        raise parser._make_error("Expected member name in __builtin_offsetof", token)
    assert isinstance(token.lexeme, str)
    parts: list[str] = [token.lexeme]
    parser._advance()
    while parser._check_punct("."):
        parser._advance()
        token = parser._current()
        if token.kind != TokenKind.IDENT:
            raise parser._make_error(
                "Expected member name after '.' in __builtin_offsetof",
                token,
            )
        assert isinstance(token.lexeme, str)
        parts.append(token.lexeme)
        parser._advance()
    parser._expect_punct(")")
    return BuiltinOffsetofExpr(type_spec=type_spec, member=".".join(parts))


def parse_builtin_types_compatible_p(parser: "Parser") -> BuiltinTypesCompatExpr:
    parser._advance()
    parser._expect_punct("(")
    type1 = parser._parse_type_name()
    parser._expect_punct(",")
    type2 = parser._parse_type_name()
    parser._expect_punct(")")
    return BuiltinTypesCompatExpr(type1=type1, type2=type2)


def parse_generic_expr(parser: "Parser") -> GenericExpr:
    parser._advance()
    parser._expect_punct("(")
    control = parser._parse_assignment()
    parser._expect_punct(",")
    associations: list[tuple[TypeSpec | None, Expr]] = []
    association_source_locations: list[tuple[int | None, int | None]] = []
    has_default_association = False
    first_default_index = 0
    first_default_line = 0
    first_default_column = 0
    association_index = 0
    parsed_type_positions: dict[tuple[object, ...], tuple[int, Token, str]] = {}
    while True:
        association_index += 1
        assoc_type: TypeSpec | None
        if parser._check_keyword("default"):
            default_token = parser._current()
            if has_default_association:
                raise parser._make_error(
                    "Duplicate default generic association at position "
                    f"{association_index} (line {default_token.line}, column "
                    f"{default_token.column}): previous default was at position "
                    f"{first_default_index} (line {first_default_line}, "
                    f"column {first_default_column}); only one default "
                    "association is allowed",
                    parser._current(),
                )
            has_default_association = True
            first_default_index = association_index
            first_default_line = default_token.line
            first_default_column = default_token.column
            parser._advance()
            assoc_type = None
            association_source_locations.append((default_token.line, default_token.column))
        else:
            association_start_index = parser._index
            association_type_token = parser._current()
            assoc_type = _with_type_spec_source(
                parser._parse_type_name(),
                association_type_token.line,
                association_type_token.column,
            )
            association_source_locations.append(
                (association_type_token.line, association_type_token.column)
            )
            association_end_index = parser._index
            association_type_spelling = parser._format_token_span(
                association_start_index,
                association_end_index,
            )
            if not parser._type_name_uses_typedef_alias(
                association_start_index,
                association_end_index,
            ):
                type_key = parser._generic_association_type_key(assoc_type)
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
                    raise parser._make_error(
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
        parser._expect_punct(":")
        associations.append((assoc_type, parser._parse_assignment()))
        if not parser._check_punct(","):
            break
        parser._advance()
    parser._expect_punct(")")
    return GenericExpr(
        control,
        tuple(associations),
        tuple(association_source_locations),
    )


def parse_statement_expr(parser: "Parser") -> StatementExpr:
    parser._expect_punct("(")
    body = parser._parse_compound_stmt()
    parser._expect_punct(")")
    return StatementExpr(body)


def parse_string_literal(parser: "Parser") -> StringLiteral:
    token = parser._expect(TokenKind.STRING_LITERAL)
    assert isinstance(token.lexeme, str)
    prefix, body = split_string_literal(parser, token.lexeme, token)
    while parser._current().kind == TokenKind.STRING_LITERAL:
        token = parser._advance()
        assert isinstance(token.lexeme, str)
        next_prefix, next_body = split_string_literal(parser, token.lexeme, token)
        prefix = merge_string_prefix(parser, prefix, next_prefix, token)
        body += next_body
    return StringLiteral(f'{prefix}"{body}"')


def split_string_literal(parser: "Parser", lexeme: str, token: Token) -> tuple[str, str]:
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
    raise parser._make_error("Invalid string literal", token)


def merge_string_prefix(
    parser: "Parser",
    prefix: str,
    next_prefix: str,
    token: Token,
) -> str:
    if prefix == next_prefix or not next_prefix:
        return prefix
    if not prefix:
        return next_prefix
    raise parser._make_error("Incompatible string literal prefixes", token)


def format_token_span(parser: "Parser", start: int, end: int) -> str:
    parts: list[str] = []
    for token in parser._tokens[start:end]:
        if token.lexeme is not None:
            parts.append(str(token.lexeme))
    return " ".join(parts)


def type_name_uses_typedef_alias(parser: "Parser", start: int, end: int) -> bool:
    for token in parser._tokens[start:end]:
        if (
            token.kind == TokenKind.IDENT
            and isinstance(token.lexeme, str)
            and parser._is_typedef_name(token.lexeme)
        ):
            return True
    return False


def _canonical_type_qualifiers(qualifiers: tuple[str, ...]) -> tuple[str, ...]:
    result: tuple[str, ...] = ()
    for qualifier in _CANONICAL_TYPE_QUALIFIER_ORDER:
        if qualifier in qualifiers:
            result = (*result, qualifier)
    for qualifier in qualifiers:
        if qualifier not in result:
            result = (*result, qualifier)
    return result


def _stable_generic_key_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, IntLiteral):
        return ("IntLiteral", value.value)
    if isinstance(value, Identifier):
        return ("Identifier", value.name)
    if isinstance(value, ArrayDecl):
        return (
            "ArrayDecl",
            _stable_generic_key_value(value.length),
            _canonical_type_qualifiers(value.qualifiers),
            value.has_static_bound,
        )
    if isinstance(value, tuple):
        items: tuple[object, ...] = ()
        for item in value:
            items = (*items, _stable_generic_key_value(item))
        return items
    return "object"


def _generic_association_declarator_op_key(
    parser: "Parser",
    op: DeclaratorOp,
) -> tuple[object, ...]:
    kind, value = op
    if kind == "arr" and isinstance(value, ArrayDecl):
        return (
            kind,
            _stable_generic_key_value(value.length),
            _canonical_type_qualifiers(value.qualifiers),
            value.has_static_bound,
        )
    if kind == "func" and isinstance(value, tuple):
        function_declarator = cast(FunctionDeclarator, value)
        params = function_declarator[0]
        is_variadic = function_declarator[1]
        if params is None:
            param_keys: tuple[object, ...] | None = None
        else:
            param_keys = ()
            for param in params:
                param_keys = (*param_keys, generic_association_type_key(parser, param))
        return (kind, param_keys, is_variadic)
    return (kind, _stable_generic_key_value(value))


def generic_association_type_key(parser: "Parser", type_spec: TypeSpec) -> tuple[object, ...]:
    enum_member_keys: tuple[object, ...] = ()
    for name, expr in type_spec.enum_members:
        enum_member_keys = (*enum_member_keys, (name, _stable_generic_key_value(expr)))
    record_member_keys: tuple[object, ...] = ()
    for member in type_spec.record_members:
        record_member_keys = (
            *record_member_keys,
            (
                generic_association_type_key(parser, member.type_spec),
                member.name,
                member.alignment,
                _stable_generic_key_value(member.bit_width_expr),
            ),
        )
    declarator_op_keys: tuple[object, ...] = ()
    for op in type_spec.declarator_ops:
        declarator_op_keys = (
            *declarator_op_keys,
            _generic_association_declarator_op_key(parser, op),
        )
    return (
        type_spec.name,
        _canonical_type_qualifiers(type_spec.qualifiers),
        type_spec.is_atomic,
        None
        if type_spec.atomic_target is None
        else generic_association_type_key(parser, type_spec.atomic_target),
        type_spec.enum_tag,
        enum_member_keys,
        type_spec.record_tag,
        record_member_keys,
        declarator_op_keys,
    )
