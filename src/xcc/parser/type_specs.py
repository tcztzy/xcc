from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from xcc.ast import ArrayDecl, Expr, RecordMemberDecl, StorageClass, TypeSpec
from xcc.lexer import Token, TokenKind

if TYPE_CHECKING:
    from . import Parser

INTEGER_TYPE_KEYWORDS = {"int", "char", "short", "long", "signed", "unsigned"}
FLOATING_TYPE_KEYWORDS = {"float", "double"}
SIMPLE_TYPE_SPEC_KEYWORDS = {
    "int",
    "char",
    "short",
    "long",
    "signed",
    "unsigned",
    "float",
    "double",
    "void",
}
TYPEOF_KEYWORDS = {
    "typeof",
    "typeof_unqual",
    "__typeof__",
    "__typeof",
    "__typeof_unqual__",
    "__typeof_unqual",
}
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict", "__restrict", "__restrict__"}
_NULLABLE_QUALIFIERS = {
    "_Nullable",
    "_Nonnull",
    "_Null_unspecified",
    "__nullable",
    "__nonnull",
    "__null_unspecified",
}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned", "constexpr"}
_GNU_EXTENSION_TYPES = {
    "bool",
    "_Float16",
    "_Float32",
    "_Float64",
    "_Float128",
    "_Float32x",
    "_Float64x",
    "__bf16",
    "__fp16",
    "__int128",
    "__uint128",
    "__int128_t",
    "__uint128_t",
}
_GNU_EXTENSION_INT_TYPES = {"__int128", "__uint128", "__int128_t", "__uint128_t"}
STORAGE_CLASS_KEYWORDS = {"auto", "register", "static", "extern", "typedef"}
FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
POINTER_OP: DeclaratorOp = ("ptr", 0)


def _merge_unique_qualifiers(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    merged: tuple[str, ...] = ()
    for qualifier in left:
        if qualifier not in merged:
            merged = (*merged, qualifier)
    for qualifier in right:
        if qualifier not in merged:
            merged = (*merged, qualifier)
    return merged


def _normalize_type_qualifier(lexeme: str) -> str:
    if lexeme == "__restrict" or lexeme == "__restrict__":
        return "restrict"
    return lexeme


def _consume_trailing_type_qualifiers(
    parser: "Parser",
    qualifiers: tuple[str, ...],
) -> tuple[str, ...]:
    p = cast(Any, parser)
    trailing = p._consume_type_qualifiers()
    return _merge_unique_qualifiers(qualifiers, trailing)


def _apply_pointer_depth(parser: "Parser", type_spec: TypeSpec, pointer_depth: int) -> TypeSpec:
    if pointer_depth == 0:
        return type_spec
    p = cast(Any, parser)
    return p._build_declarator_type(type_spec, _pointer_ops(pointer_depth))


def _pointer_ops(pointer_depth: int) -> tuple[DeclaratorOp, ...]:
    ops: tuple[DeclaratorOp, ...] = ()
    for _ in range(pointer_depth):
        ops = ops + (POINTER_OP,)
    return ops


def _parse_optional_pointer_depth(parser: "Parser", parse_pointer_depth: bool) -> int:
    if not parse_pointer_depth:
        return 0
    p = cast(Any, parser)
    return p._parse_pointer_depth()


def _has_pointer_declarator_op(type_spec: TypeSpec) -> bool:
    # AOT subset: keep this as a loop instead of any(generator).
    for kind, _ in type_spec.declarator_ops:  # noqa: SIM110
        if kind == "ptr":
            return True
    return False


@dataclass
class ParserError(ValueError):
    message: str
    token: Token

    def __str__(self) -> str:
        return f"{self.message} at {self.token.line}:{self.token.column}"


@dataclass(frozen=True)
class DeclSpecInfo:
    is_typedef: bool = False
    storage_class: StorageClass | None = None
    storage_class_token: Token | None = None
    alignment: int | None = None
    alignment_token: Token | None = None
    is_thread_local: bool = False
    is_inline: bool = False
    is_noreturn: bool = False


def unsupported_type_message(context: str, token: Token) -> str:
    token_text = str(token.lexeme)
    if token.kind == TokenKind.IDENT:
        if context == "type-name":
            return f"Unknown type name: '{token_text}'"
        return f"Unknown declaration type name: '{token_text}'"
    if token.kind == TokenKind.KEYWORD:
        if context == "type-name":
            return f"Unsupported type name: '{token_text}'"
        return f"Unsupported declaration type: '{token_text}'"
    token_kind = (
        unsupported_type_token_kind(token.kind)
        if isinstance(token.kind, TokenKind)
        else "unsupported token kind"
    )
    if context == "type-name":
        if token.kind == TokenKind.PUNCTUATOR:
            return unsupported_type_name_punctuator_message(token_text)
        return unsupported_type_name_token_message(token_text, token_kind)
    if token.kind == TokenKind.PUNCTUATOR:
        return unsupported_declaration_type_punctuator_message(token_text)
    return unsupported_declaration_type_token_message(token_text, token_kind)


def unsupported_type_name_token_message(token_text: str, token_kind: str) -> str:
    if token_kind == "end of input":
        return "Type name is missing before end of input"
    return f"Type name cannot start with {token_kind}: '{token_text}'"


def unsupported_declaration_type_token_message(token_text: str, token_kind: str) -> str:
    if token_kind == "end of input":
        return "Declaration type is missing before end of input"
    return f"Declaration type cannot start with {token_kind}: '{token_text}'"


_TYPE_NAME_CANNOT_START = {
    "(",
    "+",
    "++",
    "-",
    "--",
    "<",
    "<=",
    "<<",
    ">",
    ">=",
    ">>",
    "!",
    "~",
    "&",
    "&&",
    "|",
    "||",
    "^",
    "*",
    "/",
    "%",
    "%:",
    "%:%:",
    ".",
    "->",
    "...",
    "[",
    "<:",
    "#",
    "##",
    "=",
    "==",
    "!=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<=",
    ">>=",
}
_TYPE_NAME_MISSING = {
    ")",
    "{",
    "<%",
    "]",
    ":>",
    ",",
    ":",
    ";",
    "?",
    "}",
    "%>",
}


def unsupported_type_name_punctuator_message(punctuator: str) -> str:
    if punctuator in _TYPE_NAME_CANNOT_START:
        return f"Type name cannot start with '{punctuator}': expected a type specifier"
    if punctuator in _TYPE_NAME_MISSING:
        return f"Type name is missing before '{punctuator}'"
    return f"Unsupported type name punctuator: '{punctuator}'"


_DECLARATION_TYPE_CANNOT_START = {"(", "[", "<:"}
_DECLARATION_TYPE_MISSING_EXPECTED = {
    "+",
    "++",
    "-",
    "--",
    "<",
    "<=",
    "<<",
    ">",
    ">=",
    ">>",
    "!",
    "~",
    "&",
    "&&",
    "|",
    "||",
    "^",
    "/",
    "%",
    "%:",
    "%:%:",
    ".",
    "->",
    "...",
    "#",
    "##",
    "=",
    "==",
    "!=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<=",
    ">>=",
}
_DECLARATION_TYPE_MISSING = {
    ")",
    ",",
    ":",
    ";",
    "?",
    "]",
    ":>",
    "{",
    "<%",
    "}",
    "%>",
}


def unsupported_declaration_type_punctuator_message(punctuator: str) -> str:
    if punctuator in _DECLARATION_TYPE_CANNOT_START:
        return f"Declaration type cannot start with '{punctuator}': expected a type specifier"
    if punctuator == "*":
        return "Declaration type is missing before '*': pointer declarator requires a base type"
    if punctuator in _DECLARATION_TYPE_MISSING_EXPECTED:
        return f"Declaration type is missing before '{punctuator}': expected a type specifier"
    if punctuator in _DECLARATION_TYPE_MISSING:
        return f"Declaration type is missing before '{punctuator}'"
    return f"Unsupported declaration type punctuator: '{punctuator}'"


def unsupported_type_token_kind(kind: TokenKind) -> str:
    if kind == TokenKind.INT_CONST:
        return "integer constant"
    if kind == TokenKind.FLOAT_CONST:
        return "floating constant"
    if kind == TokenKind.CHAR_CONST:
        return "character constant"
    if kind == TokenKind.STRING_LITERAL:
        return "string literal"
    if kind == TokenKind.PUNCTUATOR:
        return "punctuator"
    if kind == TokenKind.HEADER_NAME:
        return "header name"
    if kind == TokenKind.PP_NUMBER:
        return "preprocessor number"
    if kind == TokenKind.EOF:
        return "end of input"
    return "token"


def parse_type_spec(
    parser: "Parser",
    *,
    parse_pointer_depth: bool = True,
    context: str = "declaration",
) -> TypeSpec:
    p = cast(Any, parser)
    qualifiers = p._consume_type_qualifiers()
    if p._check_keyword("_Atomic"):
        atomic_token = p._advance()
        if p._check_punct("("):
            atomic_base, is_qualified_atomic_target = p._parse_parenthesized_atomic_type_name()
            invalid_reason = p._classify_invalid_atomic_type(
                atomic_base,
                is_qualified_atomic_target=is_qualified_atomic_target,
            )
            if invalid_reason is not None:
                raise ParserError(
                    p._format_invalid_atomic_type_message(invalid_reason),
                    atomic_token,
                )
            atomic_type = p._mark_atomic_type_spec(atomic_base)
            qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
            if parse_pointer_depth:
                pointer_depth = p._parse_pointer_depth()
                if pointer_depth:
                    atomic_type = p._build_declarator_type(
                        atomic_type,
                        _pointer_ops(pointer_depth),
                    )
            return p._apply_type_qualifiers(atomic_type, qualifiers)
        if p._current().kind not in {TokenKind.KEYWORD, TokenKind.IDENT}:
            raise ParserError("Expected type name after _Atomic", atomic_token)
        atomic_base = p._parse_type_spec(
            parse_pointer_depth=False,
            context=context,
        )
        invalid_reason = p._classify_invalid_atomic_type(
            atomic_base,
            include_atomic=False,
        )
        if invalid_reason is not None:
            raise ParserError(
                p._format_invalid_atomic_type_message(invalid_reason),
                atomic_token,
            )
        atomic_type = p._mark_atomic_type_spec(atomic_base)
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        if parse_pointer_depth:
            pointer_depth = p._parse_pointer_depth()
            if pointer_depth:
                atomic_type = p._build_declarator_type(
                    atomic_type,
                    _pointer_ops(pointer_depth),
                )
        return p._apply_type_qualifiers(atomic_type, qualifiers)
    token = p._current()
    if token.kind == TokenKind.IDENT:
        assert isinstance(token.lexeme, str)
        if token.lexeme in _GNU_EXTENSION_TYPES:
            p._advance()
            type_spec = TypeSpec(token.lexeme)
            qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
            pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
            if pointer_depth:
                type_spec = p._build_declarator_type(
                    type_spec,
                    _pointer_ops(pointer_depth),
                )
            return p._apply_type_qualifiers(type_spec, qualifiers)
        type_spec = p._lookup_typedef(token.lexeme)
        if type_spec is None:
            raise ParserError(p._unsupported_type_message(context, token), token)
        typedef_has_declarator_ops = bool(type_spec.declarator_ops)
        p._advance()
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        if pointer_depth:
            type_spec = p._build_declarator_type(
                type_spec,
                _pointer_ops(pointer_depth),
            )
        return apply_typedef_type_qualifiers(
            type_spec,
            qualifiers,
            typedef_has_declarator_ops=typedef_has_declarator_ops,
        )
    token = p._current()
    if token.kind != TokenKind.KEYWORD:
        raise ParserError(p._unsupported_type_message(context, token), token)
    p._advance()
    if token.lexeme in TYPEOF_KEYWORDS:
        type_spec = p._parse_typeof_type_spec()
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        if pointer_depth:
            type_spec = p._build_declarator_type(
                type_spec,
                _pointer_ops(pointer_depth),
            )
        return p._apply_type_qualifiers(type_spec, qualifiers)
    if token.lexeme == "_Complex":
        if p._check_keyword("float") or p._check_keyword("double"):
            complex_base = p._advance()
            assert isinstance(complex_base.lexeme, str)
            qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
            pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
            type_spec = TypeSpec(str(complex_base.lexeme), qualifiers=qualifiers)
            return _apply_pointer_depth(p, type_spec, pointer_depth)
        if (
            p._check_keyword("long")
            and p._peek().kind == TokenKind.KEYWORD
            and p._peek().lexeme == "double"
        ):
            p._advance()
            p._advance()
            qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
            pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
            type_spec = TypeSpec("long double", qualifiers=qualifiers)
            return _apply_pointer_depth(p, type_spec, pointer_depth)
        raise ParserError(p._unsupported_type_message(context, token), token)
    if token.lexeme in FLOATING_TYPE_KEYWORDS:
        assert isinstance(token.lexeme, str)
        type_name = str(token.lexeme)
        p._reject_optional_complex_specifier(context, allow=True)
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        type_spec = TypeSpec(type_name, qualifiers=qualifiers)
        return _apply_pointer_depth(p, type_spec, pointer_depth)
    if token.lexeme == "_Bool":
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        type_spec = TypeSpec("_Bool", qualifiers=qualifiers)
        return _apply_pointer_depth(p, type_spec, pointer_depth)
    if token.lexeme in SIMPLE_TYPE_SPEC_KEYWORDS:
        assert isinstance(token.lexeme, str)
        if token.lexeme == "void":
            qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
            pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
            type_spec = TypeSpec("void", qualifiers=qualifiers)
            return _apply_pointer_depth(p, type_spec, pointer_depth)
        type_name = p._parse_integer_type_spec(token.lexeme, token, context=context)
        if type_name == "long" and p._check_keyword("double"):
            p._advance()
            type_name = "long double"
        p._reject_optional_complex_specifier(context, allow=type_name == "long double")
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        type_spec = TypeSpec(type_name, qualifiers=qualifiers)
        return _apply_pointer_depth(p, type_spec, pointer_depth)
    if token.lexeme == "enum":
        enum_tag, enum_members = p._parse_enum_spec(token)
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        type_spec = TypeSpec(
            "enum",
            qualifiers=qualifiers,
            enum_tag=enum_tag,
            enum_members=enum_members,
        )
        return _apply_pointer_depth(p, type_spec, pointer_depth)
    if token.lexeme in {"struct", "union"}:
        record_tag, record_members, has_record_body = p._parse_record_spec(
            token,
            str(token.lexeme),
        )
        qualifiers = _consume_trailing_type_qualifiers(p, qualifiers)
        pointer_depth = _parse_optional_pointer_depth(p, parse_pointer_depth)
        type_spec = TypeSpec(
            str(token.lexeme),
            qualifiers=qualifiers,
            record_tag=record_tag,
            record_members=record_members,
            has_record_body=has_record_body,
        )
        return _apply_pointer_depth(p, type_spec, pointer_depth)
    raise ParserError(p._unsupported_type_message(context, token), token)


def consume_type_qualifiers(parser: "Parser", *, allow_atomic: bool = False) -> tuple[str, ...]:
    p = cast(Any, parser)
    seen: list[str] = []
    while True:
        token = p._current()
        is_type_qualifier = token.lexeme in TYPE_QUALIFIER_KEYWORDS
        is_allowed_atomic = allow_atomic and token.lexeme == "_Atomic"
        if token.kind == TokenKind.KEYWORD and (is_type_qualifier or is_allowed_atomic):
            token = p._advance()
            lexeme = str(token.lexeme)
            qualifier = _normalize_type_qualifier(lexeme)
            if qualifier in seen:
                raise ParserError(f"Duplicate type qualifier: '{qualifier}'", token)
            seen.append(qualifier)
            continue
        if token.kind == TokenKind.IDENT and token.lexeme in _IGNORED_IDENT_TYPE_QUALIFIERS:
            # For contextual keywords like constexpr, only consume as a
            # qualifier if the next token looks like a type start.
            # If followed by ; or , or =, treat as an identifier.
            if token.lexeme == "constexpr":
                nxt = p._peek()
                if nxt.kind == TokenKind.PUNCTUATOR and nxt.lexeme in {";", ",", "="}:
                    break
            token = p._advance()
            lexeme = str(token.lexeme)
            if lexeme in seen:
                raise ParserError(f"Duplicate type qualifier: '{lexeme}'", token)
            # constexpr implies const
            seen.append("const" if lexeme == "constexpr" else lexeme)
            continue
        if p._is_ms_declspec_start():
            p._skip_ms_declspecs()
            continue
        break
    qualifiers: tuple[str, ...] = ()
    for qualifier in seen:
        if qualifier in TYPE_QUALIFIER_KEYWORDS:
            qualifiers = (*qualifiers, qualifier)
    return qualifiers


def apply_type_qualifiers(type_spec: TypeSpec, qualifiers: tuple[str, ...]) -> TypeSpec:
    if not qualifiers:
        return type_spec
    merged = _merge_unique_qualifiers(type_spec.qualifiers, qualifiers)
    return TypeSpec(
        type_spec.name,
        declarator_ops=type_spec.declarator_ops,
        qualifiers=merged,
        is_atomic=type_spec.is_atomic,
        atomic_target=type_spec.atomic_target,
        enum_tag=type_spec.enum_tag,
        enum_members=type_spec.enum_members,
        record_tag=type_spec.record_tag,
        record_members=type_spec.record_members,
        has_record_body=type_spec.has_record_body,
        typeof_expr=type_spec.typeof_expr,
    )


def apply_typedef_type_qualifiers(
    type_spec: TypeSpec,
    qualifiers: tuple[str, ...],
    *,
    typedef_has_declarator_ops: bool,
) -> TypeSpec:
    if not qualifiers:
        return type_spec
    if (
        typedef_has_declarator_ops
        and type_spec.declarator_ops
        and type_spec.declarator_ops[0][0] in {"ptr", "fn"}
    ):
        return type_spec
    return apply_type_qualifiers(type_spec, qualifiers)


def reject_optional_complex_specifier(
    parser: "Parser",
    context: str,
    *,
    allow: bool = False,
) -> None:
    p = cast(Any, parser)
    if p._check_keyword("_Complex"):
        token = p._advance()
        if allow:
            return
        raise ParserError(p._unsupported_type_message(context, token), token)


def _integer_type_invalid_order(keyword: str, current_base: str | None) -> str:
    prior = current_base if current_base is not None else "<none>"
    return f"Invalid integer type keyword order: '{keyword}' after '{prior}'"


def _consume_integer_type_keyword(
    keyword: str,
    token: Token,
    current_signedness: str | None,
    current_base: str | None,
) -> tuple[str | None, str | None]:
    if keyword in {"signed", "unsigned"}:
        if current_signedness is not None:
            raise ParserError(
                f"Duplicate integer signedness specifier: '{keyword}'",
                token,
            )
        return keyword, current_base
    if keyword == "char":
        if current_base is not None:
            raise ParserError(_integer_type_invalid_order(keyword, current_base), token)
        return current_signedness, keyword
    if keyword == "short":
        if current_base in {None, "int"}:
            return current_signedness, keyword
        raise ParserError(_integer_type_invalid_order(keyword, current_base), token)
    if keyword == "long":
        if current_base in {None, "int"}:
            return current_signedness, keyword
        if current_base == "long":
            return current_signedness, "long long"
        raise ParserError(_integer_type_invalid_order(keyword, current_base), token)
    assert keyword == "int"
    if current_base is None:
        return current_signedness, keyword
    if current_base in {"short", "long", "long long"}:
        return current_signedness, current_base
    raise ParserError(_integer_type_invalid_order(keyword, current_base), token)


def _consume_gnu_int_type(token: Token) -> str | None:
    assert isinstance(token.lexeme, str)
    if token.lexeme in _GNU_EXTENSION_INT_TYPES:
        return str(token.lexeme)
    return None


def parse_integer_type_spec(
    parser: "Parser",
    first_keyword: str,
    first_token: Token,
    *,
    context: str = "declaration",
) -> str:
    p = cast(Any, parser)
    signedness: str | None = None
    base: str | None = None

    signedness, base = _consume_integer_type_keyword(first_keyword, first_token, signedness, base)
    while p._current().kind == TokenKind.KEYWORD:
        token = p._current()
        assert isinstance(token.lexeme, str)
        if token.lexeme not in INTEGER_TYPE_KEYWORDS:
            break
        p._advance()
        signedness, base = _consume_integer_type_keyword(token.lexeme, token, signedness, base)

    if base is None and p._current().kind == TokenKind.IDENT:
        gnu_base = _consume_gnu_int_type(p._current())
        if gnu_base is not None:
            p._advance()
            base = gnu_base

    if base is None:
        base = "int"
    if base == "char":
        return "unsigned char" if signedness == "unsigned" else "char"
    if base == "short":
        return "unsigned short" if signedness == "unsigned" else "short"
    if base == "long":
        return "unsigned long" if signedness == "unsigned" else "long"
    if base == "long long":
        return "unsigned long long" if signedness == "unsigned" else "long long"
    if base in _GNU_EXTENSION_INT_TYPES:
        return f"unsigned {base}" if signedness == "unsigned" else base
    return "unsigned int" if signedness == "unsigned" else "int"


def parse_enum_spec(
    parser: "Parser",
    token: Token,
) -> tuple[str | None, tuple[tuple[str, Expr | None], ...]]:
    p = cast(Any, parser)
    enum_tag: str | None = None
    if p._current().kind == TokenKind.IDENT:
        ident = p._advance()
        assert isinstance(ident.lexeme, str)
        enum_tag = ident.lexeme
    # C23 enum : underlying_type (or Clang/C++ extension)
    if p._check_punct(":"):
        p._advance()
        p._parse_type_spec()
    enum_members: tuple[tuple[str, Expr | None], ...] = ()
    if p._check_punct("{"):
        enum_members = p._parse_enum_members()
    if enum_tag is None and not enum_members:
        raise ParserError("Expected enum tag or definition", token)
    return enum_tag, enum_members


def parse_enum_members(parser: "Parser") -> tuple[tuple[str, Expr | None], ...]:
    p = cast(Any, parser)
    p._expect_punct("{")
    if p._check_punct("}"):
        raise ParserError("Expected enumerator", p._current())
    members: list[tuple[str, Expr | None]] = []
    while True:
        members.append(p._parse_enum_member())
        if not p._check_punct(","):
            break
        p._advance()
        if p._check_punct("}"):
            break
    p._expect_punct("}")
    return tuple(members)


def parse_enum_member(parser: "Parser") -> tuple[str, Expr | None]:
    p = cast(Any, parser)
    token = p._expect(TokenKind.IDENT)
    assert isinstance(token.lexeme, str)
    p._skip_decl_attributes()
    if not p._check_punct("="):
        return token.lexeme, None
    p._advance()
    return token.lexeme, p._parse_conditional()


def parse_record_spec(
    parser: "Parser",
    token: Token,
    kind: str,
) -> tuple[str | None, tuple[RecordMemberDecl, ...], bool]:
    p = cast(Any, parser)
    p._skip_decl_attributes()
    record_tag: str | None = None
    if p._current().kind == TokenKind.IDENT:
        ident = p._advance()
        assert isinstance(ident.lexeme, str)
        record_tag = ident.lexeme
    record_members: tuple[RecordMemberDecl, ...] = ()
    has_record_body = False
    if p._check_punct("{"):
        has_record_body = True
        record_members = p._parse_record_members()
    if record_tag is None and not record_members and not has_record_body:
        raise ParserError(f"Expected {kind} tag or definition", token)
    return record_tag, record_members, has_record_body


def parse_record_members(parser: "Parser") -> tuple[RecordMemberDecl, ...]:
    p = cast(Any, parser)
    p._expect_punct("{")
    members: list[RecordMemberDecl] = []
    while not p._check_punct("}"):
        if p._check_keyword("_Static_assert") or p._is_static_assert_ident():
            p._parse_static_assert_decl()
            continue
        members.extend(p._parse_record_member_declaration())
    p._expect_punct("}")
    return tuple(members)


def parse_record_member_declaration(parser: "Parser") -> list[RecordMemberDecl]:
    p = cast(Any, parser)
    p._skip_extension_markers()
    decl_specs = p._consume_decl_specifiers()
    if decl_specs.is_typedef or decl_specs.storage_class not in {None, "typedef"}:
        raise ParserError("Expected type specifier", p._current())
    if decl_specs.is_thread_local or decl_specs.is_inline or decl_specs.is_noreturn:
        raise ParserError(
            p._invalid_decl_specifier_message("record member", decl_specs),
            p._current(),
        )
    base_type = p._parse_type_spec(parse_pointer_depth=False)
    p._skip_type_qualifiers()
    if p._check_punct(";"):
        if decl_specs.alignment is not None:
            raise ParserError(
                p._invalid_alignment_specifier_message(
                    "record member declaration",
                ),
                decl_specs.alignment_token or p._current(),
            )
        if base_type.name in {"struct", "union"}:
            p._advance()
            return [RecordMemberDecl(base_type, None)]
        raise p._expected_identifier_error()
    members: list[RecordMemberDecl] = []
    more_members = True
    while more_members:
        name, declarator_ops = p._parse_declarator(
            allow_abstract=True,
            allow_vla=True,
            allow_flexible_array=True,
        )
        bit_width_expr: Expr | None = None
        if p._check_punct(":"):
            p._advance()
            bit_width_expr = p._parse_conditional()
        p._skip_decl_attributes()
        if name is None and bit_width_expr is None:
            raise p._expected_identifier_error()
        member_type = p._build_declarator_type(base_type, declarator_ops)
        if decl_specs.alignment is not None and p._is_function_object_type(member_type):
            raise ParserError(
                p._invalid_alignment_specifier_message(
                    "record member declaration",
                ),
                decl_specs.alignment_token or p._current(),
            )
        if p._is_invalid_void_object_type(member_type):
            raise ParserError(
                p._invalid_object_type_message("record member declaration", "void"),
                p._current(),
            )
        members.append(
            RecordMemberDecl(
                member_type,
                name,
                decl_specs.alignment,
                bit_width_expr=bit_width_expr,
            )
        )
        if p._check_punct(","):
            p._advance()
        else:
            more_members = False
    p._expect_punct(";")
    return members


def consume_decl_specifiers(parser: "Parser") -> DeclSpecInfo:
    p = cast(Any, parser)
    storage_class: StorageClass | None = None
    storage_class_token: Token | None = None
    alignment: int | None = None
    alignment_token: Token | None = None
    is_thread_local = False
    is_inline = False
    is_noreturn = False
    while True:
        attr_found, attr_alignment, attr_alignment_token = p._consume_decl_attribute_alignment()
        if attr_found:
            if attr_alignment is not None:
                current_alignment: int = 0
                if alignment is not None:
                    current_alignment = cast(int, alignment)
                if alignment is None or attr_alignment > current_alignment:
                    alignment = attr_alignment
                    alignment_token = attr_alignment_token
            continue
        current = p._current()
        if current.kind == TokenKind.KEYWORD:
            lexeme = str(current.lexeme)
        elif current.kind == TokenKind.IDENT and current.lexeme in {
            "__thread",
            "__inline",
            "__inline__",
        }:
            lexeme = "_Thread_local" if current.lexeme == "__thread" else "inline"
        else:
            break
        if lexeme in STORAGE_CLASS_KEYWORDS:
            if storage_class is not None:
                raise ParserError(f"Duplicate storage class specifier: '{lexeme}'", current)
            storage_class = cast(StorageClass, lexeme)
            storage_class_token = current
            p._advance()
            continue
        if lexeme == "_Thread_local":
            if is_thread_local:
                raise ParserError("Duplicate thread-local specifier: '_Thread_local'", current)
            is_thread_local = True
            p._advance()
            continue
        if lexeme == "inline":
            if is_inline:
                raise ParserError("Duplicate function specifier: 'inline'", current)
            is_inline = True
            p._advance()
            continue
        if lexeme == "_Noreturn":
            if is_noreturn:
                raise ParserError("Duplicate function specifier: '_Noreturn'", current)
            is_noreturn = True
            p._advance()
            continue
        if lexeme == "_Alignas":
            if alignment_token is None:
                alignment_token = current
            current_alignment = p._consume_alignas_specifier()
            previous_alignment: int = 0
            if alignment is not None:
                previous_alignment = cast(int, alignment)
            if alignment is None or current_alignment > previous_alignment:
                alignment = current_alignment
            continue
        # _Alignas can appear after type qualifiers
        # (e.g. ``static const _Alignas(16) char x``).  Peek past
        # qualifiers: if _Alignas follows, skip them and loop again;
        # otherwise leave them for _parse_type_spec to consume.
        if lexeme in TYPE_QUALIFIER_KEYWORDS or (lexeme == "_Atomic" and not p._check_punct("(")):
            saved_index = p._index
            skip_type_qualifiers(p)
            if p._current().kind == TokenKind.KEYWORD and p._current().lexeme == "_Alignas":
                continue
            p._index = saved_index
        break
    return DeclSpecInfo(
        is_typedef=storage_class == "typedef",
        storage_class=storage_class,
        storage_class_token=storage_class_token,
        alignment=alignment,
        alignment_token=alignment_token,
        is_thread_local=is_thread_local,
        is_inline=is_inline,
        is_noreturn=is_noreturn,
    )


def reject_invalid_alignment_context(
    parser: "Parser",
    alignment: int | None,
    alignment_token: Token | None,
    *,
    context: str,
    allow: bool,
) -> None:
    p = cast(Any, parser)
    if alignment is None or allow:
        return
    raise ParserError(
        p._invalid_alignment_specifier_message(context),
        alignment_token or p._current(),
    )


def consume_alignas_specifier(parser: "Parser") -> int:
    p = cast(Any, parser)
    token = p._current()
    p._advance()
    p._expect_punct("(")
    if p._try_parse_type_name():
        base_type = p._parse_type_spec()
        name, declarator_ops = p._parse_declarator(allow_abstract=True)
        assert name is None
        type_spec = p._build_declarator_type(base_type, declarator_ops)
        p._expect_punct(")")
        alignment = p._alignof_type_spec(type_spec)
        if alignment is None:
            raise ParserError(
                "Invalid alignment specifier: _Alignas type operand must denote an object type",
                token,
            )
        return alignment
    expr = p._parse_conditional()
    alignment = p._eval_array_size_expr(expr)
    if alignment is None:
        raise ParserError(
            "Invalid alignment specifier: _Alignas expression operand must be an "
            "integer constant expression",
            token,
        )
    if alignment <= 0:
        raise ParserError(
            "Invalid alignment specifier: _Alignas expression operand must be positive",
            token,
        )
    if (alignment & (alignment - 1)) != 0:
        raise ParserError(
            "Invalid alignment specifier: _Alignas expression operand must evaluate "
            "to a power of two",
            token,
        )
    p._expect_punct(")")
    return alignment


def skip_type_qualifiers(parser: "Parser", *, allow_atomic: bool = False) -> bool:
    p = cast(Any, parser)
    found = False
    while True:
        token = p._current()
        is_type_qualifier = token.lexeme in TYPE_QUALIFIER_KEYWORDS
        is_allowed_atomic = allow_atomic and token.lexeme == "_Atomic"
        if token.kind == TokenKind.KEYWORD and (is_type_qualifier or is_allowed_atomic):
            found = True
            p._advance()
            continue
        is_nullable_qualifier = token.lexeme in _NULLABLE_QUALIFIERS
        is_ignored_ident_qualifier = token.lexeme in _IGNORED_IDENT_TYPE_QUALIFIERS
        if token.kind == TokenKind.IDENT and (is_nullable_qualifier or is_ignored_ident_qualifier):
            # Contextual keywords like constexpr: treat as identifier if
            # followed by ;, ,, or =, matching consume_type_qualifiers.
            if token.lexeme == "constexpr":
                nxt = p._peek()
                if nxt.kind == TokenKind.PUNCTUATOR and nxt.lexeme in {";", ",", "="}:
                    break
                found = True
                p._advance()
                continue
            found = True
            p._advance()
            continue
        if p._is_ms_declspec_start():
            found = True
            p._skip_ms_declspecs()
            continue
        break
    return found


def is_tag_or_definition_decl(type_spec: TypeSpec) -> bool:
    if type_spec.name == "enum":
        return type_spec.enum_tag is not None or bool(type_spec.enum_members)
    if type_spec.name in {"struct", "union"}:
        return type_spec.record_tag is not None or bool(type_spec.record_members)
    return False


def is_function_object_type(type_spec: TypeSpec) -> bool:
    return bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "fn"


def define_enum_member_names(parser: "Parser", type_spec: TypeSpec) -> None:
    p = cast(Any, parser)
    value = -1
    for member_name, value_expr in type_spec.enum_members:
        if value_expr is None:
            value += 1
        else:
            evaluated = p._eval_array_size_expr(value_expr)
            if evaluated is None:
                p._define_ordinary_name(member_name)
                continue
            value = evaluated
        p._define_ordinary_constant(member_name, value)


def mark_atomic_type_spec(type_spec: TypeSpec) -> TypeSpec:
    if type_spec.is_atomic:
        return type_spec
    return TypeSpec(
        type_spec.name,
        declarator_ops=type_spec.declarator_ops,
        qualifiers=type_spec.qualifiers,
        is_atomic=True,
        atomic_target=type_spec,
        enum_tag=type_spec.enum_tag,
        enum_members=type_spec.enum_members,
        record_tag=type_spec.record_tag,
        record_members=type_spec.record_members,
        has_record_body=type_spec.has_record_body,
        typeof_expr=type_spec.typeof_expr,
    )


def format_invalid_atomic_type_message(reason: str) -> str:
    return f"Invalid atomic type: {reason}"


def classify_invalid_atomic_type(
    type_spec: TypeSpec,
    *,
    is_qualified_atomic_target: bool = False,
    include_atomic: bool = True,
) -> str | None:
    has_pointer_op = _has_pointer_declarator_op(type_spec)
    if is_qualified_atomic_target or (type_spec.qualifiers and not has_pointer_op):
        return "qualified"
    if include_atomic and type_spec.is_atomic:
        return "atomic"
    if bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "arr":
        return "array"
    if bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "fn":
        return "function"
    return None


def is_invalid_void_object_type(type_spec: TypeSpec) -> bool:
    if type_spec.name != "void":
        return False
    return not _has_pointer_declarator_op(type_spec)


def is_invalid_void_parameter_type(type_spec: TypeSpec) -> bool:
    if type_spec.name != "void":
        return False
    return not type_spec.declarator_ops
