from typing import Any, cast

from xcc.ast import ArrayDecl, Expr, RecordMemberDecl, StorageClass, TypeSpec
from xcc.lexer import Token, TokenKind
from xcc.parser.model import DeclSpecInfo, ParserError

INTEGER_TYPE_KEYWORDS = {"int", "char", "short", "long", "signed", "unsigned"}
FLOATING_TYPE_KEYWORDS = {"float", "double"}
SIMPLE_TYPE_SPEC_KEYWORDS = INTEGER_TYPE_KEYWORDS | FLOATING_TYPE_KEYWORDS | {"void"}
TYPEOF_KEYWORDS = {"typeof", "typeof_unqual", "__typeof__"}
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict"}
_NULLABLE_QUALIFIERS = {"_Nullable", "_Nonnull", "_Null_unspecified"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}
_GNU_EXTENSION_TYPES = {
    "_Float16",
    "_Float32",
    "_Float64",
    "_Float128",
    "_Float32x",
    "_Float64x",
    "__bf16",
    "__fp16",
    "__int128_t",
    "__uint128_t",
}
STORAGE_CLASS_KEYWORDS = {"auto", "register", "static", "extern", "typedef"}
FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
POINTER_OP: DeclaratorOp = ("ptr", 0)


def parse_type_spec(
    parser: object,
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
            if parse_pointer_depth:
                pointer_depth = p._parse_pointer_depth()
                if pointer_depth:
                    atomic_type = p._build_declarator_type(
                        atomic_type,
                        (POINTER_OP,) * pointer_depth,
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
        if parse_pointer_depth:
            pointer_depth = p._parse_pointer_depth()
            if pointer_depth:
                atomic_type = p._build_declarator_type(
                    atomic_type,
                    (POINTER_OP,) * pointer_depth,
                )
        return p._apply_type_qualifiers(atomic_type, qualifiers)
    token = p._current()
    if token.kind == TokenKind.IDENT:
        assert isinstance(token.lexeme, str)
        if token.lexeme in _GNU_EXTENSION_TYPES:
            p._advance()
            type_spec = TypeSpec(token.lexeme)
            pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
            if pointer_depth:
                type_spec = p._build_declarator_type(
                    type_spec,
                    (POINTER_OP,) * pointer_depth,
                )
            return p._apply_type_qualifiers(type_spec, qualifiers)
        type_spec = p._lookup_typedef(token.lexeme)
        if type_spec is None:
            raise ParserError(p._unsupported_type_message(context, token), token)
        p._advance()
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        if pointer_depth:
            type_spec = p._build_declarator_type(
                type_spec,
                (POINTER_OP,) * pointer_depth,
            )
        return p._apply_type_qualifiers(type_spec, qualifiers)
    token = p._current()
    if token.kind != TokenKind.KEYWORD:
        raise ParserError(p._unsupported_type_message(context, token), token)
    p._advance()
    if token.lexeme in TYPEOF_KEYWORDS:
        if p._std == "c11":
            raise ParserError("typeof is a GNU extension", token)
        type_spec = p._parse_typeof_type_spec()
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        if pointer_depth:
            type_spec = p._build_declarator_type(
                type_spec,
                (POINTER_OP,) * pointer_depth,
            )
        return p._apply_type_qualifiers(type_spec, qualifiers)
    if token.lexeme == "_Complex":
        if p._check_keyword("float") or p._check_keyword("double"):
            complex_base = p._advance()
            assert isinstance(complex_base.lexeme, str)
            pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec(str(complex_base.lexeme), pointer_depth, qualifiers=qualifiers)
        if (
            p._check_keyword("long")
            and p._peek().kind == TokenKind.KEYWORD
            and p._peek().lexeme == "double"
        ):
            p._advance()
            p._advance()
            pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec("long double", pointer_depth, qualifiers=qualifiers)
        raise ParserError(p._unsupported_type_message(context, token), token)
    if token.lexeme in FLOATING_TYPE_KEYWORDS:
        assert isinstance(token.lexeme, str)
        type_name = str(token.lexeme)
        p._reject_optional_complex_specifier(context, allow=True)
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        return TypeSpec(type_name, pointer_depth, qualifiers=qualifiers)
    if token.lexeme == "_Bool":
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        return TypeSpec("_Bool", pointer_depth, qualifiers=qualifiers)
    if token.lexeme in SIMPLE_TYPE_SPEC_KEYWORDS:
        assert isinstance(token.lexeme, str)
        if token.lexeme == "void":
            pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec("void", pointer_depth, qualifiers=qualifiers)
        type_name = p._parse_integer_type_spec(token.lexeme, token, context=context)
        if type_name == "long" and p._check_keyword("double"):
            p._advance()
            type_name = "long double"
        p._reject_optional_complex_specifier(context, allow=type_name == "long double")
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        return TypeSpec(type_name, pointer_depth, qualifiers=qualifiers)
    if token.lexeme == "enum":
        enum_tag, enum_members = p._parse_enum_spec(token)
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        return TypeSpec(
            "enum",
            pointer_depth,
            qualifiers=qualifiers,
            enum_tag=enum_tag,
            enum_members=enum_members,
        )
    if token.lexeme in {"struct", "union"}:
        record_tag, record_members, has_record_body = p._parse_record_spec(
            token,
            str(token.lexeme),
        )
        pointer_depth = p._parse_pointer_depth() if parse_pointer_depth else 0
        return TypeSpec(
            str(token.lexeme),
            pointer_depth,
            qualifiers=qualifiers,
            record_tag=record_tag,
            record_members=record_members,
            has_record_body=has_record_body,
        )
    raise ParserError(p._unsupported_type_message(context, token), token)


def consume_type_qualifiers(parser: object, *, allow_atomic: bool = False) -> tuple[str, ...]:
    p = cast(Any, parser)
    qualifiers = TYPE_QUALIFIER_KEYWORDS | ({"_Atomic"} if allow_atomic else set())
    seen: list[str] = []
    while True:
        token = p._current()
        if token.kind == TokenKind.KEYWORD and token.lexeme in qualifiers:
            token = p._advance()
            lexeme = str(token.lexeme)
            if lexeme in seen:
                raise ParserError(f"Duplicate type qualifier: '{lexeme}'", token)
            seen.append(lexeme)
            continue
        if token.kind == TokenKind.IDENT and token.lexeme in _IGNORED_IDENT_TYPE_QUALIFIERS:
            token = p._advance()
            lexeme = str(token.lexeme)
            if lexeme in seen:
                raise ParserError(f"Duplicate type qualifier: '{lexeme}'", token)
            seen.append(lexeme)
            continue
        if p._is_ms_declspec_start():
            p._skip_ms_declspecs()
            continue
        break
    return tuple(qualifier for qualifier in seen if qualifier in qualifiers)


def apply_type_qualifiers(type_spec: TypeSpec, qualifiers: tuple[str, ...]) -> TypeSpec:
    if not qualifiers:
        return type_spec
    merged = tuple(dict.fromkeys((*type_spec.qualifiers, *qualifiers)))
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
        typeof_expr=type_spec.typeof_expr,
    )


def reject_optional_complex_specifier(
    parser: object,
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


def parse_integer_type_spec(
    parser: object,
    first_keyword: str,
    first_token: Token,
    *,
    context: str = "declaration",
) -> str:
    del context
    p = cast(Any, parser)
    signedness: str | None = None
    base: str | None = None

    def invalid_order(keyword: str, *, current_base: str | None) -> str:
        prior = current_base if current_base is not None else "<none>"
        return f"Invalid integer type keyword order: '{keyword}' after '{prior}'"

    def consume(keyword: str, token: Token) -> None:
        nonlocal signedness, base
        if keyword in {"signed", "unsigned"}:
            if signedness is not None:
                raise ParserError(
                    f"Duplicate integer signedness specifier: '{keyword}'",
                    token,
                )
            signedness = keyword
            return
        if keyword == "char":
            if base is not None:
                raise ParserError(invalid_order(keyword, current_base=base), token)
            base = keyword
            return
        if keyword == "short":
            if base in {None, "int"}:
                base = keyword
                return
            raise ParserError(invalid_order(keyword, current_base=base), token)
        if keyword == "long":
            if base in {None, "int"}:
                base = keyword
                return
            if base == "long":
                base = "long long"
                return
            raise ParserError(invalid_order(keyword, current_base=base), token)
        assert keyword == "int"
        if base is None:
            base = keyword
            return
        if base in {"short", "long", "long long"}:
            return
        raise ParserError(invalid_order(keyword, current_base=base), token)

    consume(first_keyword, first_token)
    while p._current().kind == TokenKind.KEYWORD:
        token = p._current()
        assert isinstance(token.lexeme, str)
        if token.lexeme not in INTEGER_TYPE_KEYWORDS:
            break
        p._advance()
        consume(token.lexeme, token)

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
    return "unsigned int" if signedness == "unsigned" else "int"


def parse_enum_spec(
    parser: object,
    token: Token,
) -> tuple[str | None, tuple[tuple[str, Expr | None], ...]]:
    p = cast(Any, parser)
    enum_tag: str | None = None
    if p._current().kind == TokenKind.IDENT:
        ident = p._advance()
        assert isinstance(ident.lexeme, str)
        enum_tag = ident.lexeme
    enum_members: tuple[tuple[str, Expr | None], ...] = ()
    if p._check_punct("{"):
        enum_members = p._parse_enum_members()
    if enum_tag is None and not enum_members:
        raise ParserError("Expected enum tag or definition", token)
    return enum_tag, enum_members


def parse_enum_members(parser: object) -> tuple[tuple[str, Expr | None], ...]:
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


def parse_enum_member(parser: object) -> tuple[str, Expr | None]:
    p = cast(Any, parser)
    token = p._expect(TokenKind.IDENT)
    assert isinstance(token.lexeme, str)
    if not p._check_punct("="):
        return token.lexeme, None
    p._advance()
    return token.lexeme, p._parse_conditional()


def parse_record_spec(
    parser: object,
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


def parse_record_members(parser: object) -> tuple[RecordMemberDecl, ...]:
    p = cast(Any, parser)
    p._expect_punct("{")
    members: list[RecordMemberDecl] = []
    while not p._check_punct("}"):
        members.extend(p._parse_record_member_declaration())
    p._expect_punct("}")
    return tuple(members)


def parse_record_member_declaration(parser: object) -> list[RecordMemberDecl]:
    p = cast(Any, parser)
    decl_specs = p._consume_decl_specifiers()
    if decl_specs.is_typedef or decl_specs.storage_class not in {None, "typedef"}:
        raise ParserError("Expected type specifier", p._current())
    if decl_specs.is_thread_local or decl_specs.is_inline or decl_specs.is_noreturn:
        raise ParserError(
            p._invalid_decl_specifier_message("record member", decl_specs),
            p._current(),
        )
    base_type = p._parse_type_spec()
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
    while True:
        name, declarator_ops = p._parse_declarator(
            allow_abstract=True,
            allow_flexible_array=True,
        )
        bit_width_expr: Expr | None = None
        if p._check_punct(":"):
            p._advance()
            bit_width_expr = p._parse_conditional()
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
        if not p._check_punct(","):
            break
        p._advance()
    p._expect_punct(";")
    return members


def consume_decl_specifiers(parser: object) -> DeclSpecInfo:
    p = cast(Any, parser)
    storage_class: str | None = None
    storage_class_token: Token | None = None
    alignment: int | None = None
    alignment_token: Token | None = None
    is_thread_local = False
    is_inline = False
    is_noreturn = False
    while True:
        p._skip_decl_attributes()
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
            if alignment is None or current_alignment > alignment:
                alignment = current_alignment
            continue
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
    parser: object,
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


def consume_alignas_specifier(parser: object) -> int:
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


def skip_type_qualifiers(parser: object, *, allow_atomic: bool = False) -> bool:
    p = cast(Any, parser)
    qualifiers = TYPE_QUALIFIER_KEYWORDS | ({"_Atomic"} if allow_atomic else set())
    found = False
    while True:
        if p._current().kind == TokenKind.KEYWORD and p._current().lexeme in qualifiers:
            found = True
            p._advance()
            continue
        if p._current().kind == TokenKind.IDENT and p._current().lexeme in (
            _NULLABLE_QUALIFIERS | _IGNORED_IDENT_TYPE_QUALIFIERS
        ):
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


def define_enum_member_names(parser: object, type_spec: TypeSpec) -> None:
    p = cast(Any, parser)
    for member_name, _ in type_spec.enum_members:
        p._define_ordinary_name(member_name)


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
    if is_qualified_atomic_target:
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
    return not any(kind == "ptr" for kind, _ in type_spec.declarator_ops)


def is_invalid_void_parameter_type(type_spec: TypeSpec) -> bool:
    if type_spec.name != "void":
        return False
    return not type_spec.declarator_ops
