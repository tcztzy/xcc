from typing import Any, cast

from xcc.ast import ArrayDecl, Expr, IntLiteral, TypeSpec
from xcc.lexer import Token, TokenKind
from xcc.parser.diagnostics import (
    _array_size_literal_error,
    _array_size_non_ice_error,
)
from xcc.parser.model import ParserError

TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}
FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
POINTER_OP: DeclaratorOp = ("ptr", 0)


def parse_pointer_depth(parser: object) -> int:
    p = cast(Any, parser)
    p._skip_type_qualifiers()
    pointer_depth = 0
    while p._check_punct("*"):
        p._advance()
        p._skip_type_qualifiers(allow_atomic=True)
        pointer_depth += 1
    return pointer_depth


def parse_parenthesized_atomic_type_name(parser: object) -> tuple[TypeSpec, bool]:
    p = cast(Any, parser)
    p._expect_punct("(")
    base_is_qualified_typedef = False
    current = p._current()
    if current.kind == TokenKind.IDENT and isinstance(current.lexeme, str):
        base_is_qualified_typedef = p._is_top_level_qualified_typedef(current.lexeme)
    base_has_leading_qualifier = (
        p._current().kind == TokenKind.KEYWORD and p._current().lexeme in TYPE_QUALIFIER_KEYWORDS
    )
    base_type = p._parse_type_spec(parse_pointer_depth=False, context="type-name")
    name, declarator_ops, declarator_has_prefix_qualifier, top_pointer_is_qualified = (
        p._parse_atomic_type_name_declarator(allow_gnu_attributes=True)
    )
    if name is not None:
        raise ParserError(
            f"Type name cannot declare identifier '{name}'",
            p._current(),
        )
    p._expect_punct(")")
    type_spec = p._build_declarator_type(base_type, declarator_ops)
    is_qualified = p._is_top_level_qualified_type_name(
        base_has_leading_qualifier=base_has_leading_qualifier,
        base_is_qualified_typedef=base_is_qualified_typedef,
        declarator_has_prefix_qualifier=declarator_has_prefix_qualifier,
        declarator_ops=declarator_ops,
        top_pointer_is_qualified=top_pointer_is_qualified,
    )
    return type_spec, is_qualified


def parse_atomic_type_name_declarator(
    parser: object,
    *,
    allow_abstract: bool = True,
    allow_gnu_attributes: bool = False,
) -> tuple[str | None, tuple[DeclaratorOp, ...], bool, bool]:
    p = cast(Any, parser)
    declarator_has_prefix_qualifier = p._skip_type_qualifiers(allow_atomic=True)
    p._skip_type_name_attributes(allow_gnu_attributes=allow_gnu_attributes)
    p._skip_calling_convention_identifiers_before_pointer()
    pointer_qualifiers: list[bool] = []
    while p._check_punct("*"):
        p._advance()
        pointer_qualifiers.append(p._skip_type_qualifiers(allow_atomic=True))
        p._skip_type_name_attributes(allow_gnu_attributes=allow_gnu_attributes)
        p._skip_calling_convention_identifiers_after_pointer()
    name, direct_ops, direct_top_pointer_is_qualified = p._parse_atomic_type_name_direct_declarator(
        allow_abstract=allow_abstract,
        allow_gnu_attributes=allow_gnu_attributes,
    )
    declarator_ops = direct_ops + (POINTER_OP,) * len(pointer_qualifiers)
    top_pointer_is_qualified = direct_top_pointer_is_qualified
    if not direct_ops and pointer_qualifiers:
        top_pointer_is_qualified = pointer_qualifiers[-1]
    return (
        name,
        declarator_ops,
        declarator_has_prefix_qualifier,
        top_pointer_is_qualified,
    )


def parse_atomic_type_name_direct_declarator(
    parser: object,
    *,
    allow_abstract: bool = True,
    allow_gnu_attributes: bool = False,
) -> tuple[str | None, tuple[DeclaratorOp, ...], bool]:
    p = cast(Any, parser)
    name: str | None
    declarator_ops: tuple[DeclaratorOp, ...]
    top_pointer_is_qualified = False
    p._skip_type_name_attributes(allow_gnu_attributes=allow_gnu_attributes)
    if p._current().kind == TokenKind.IDENT:
        token = p._advance()
        assert isinstance(token.lexeme, str)
        name = token.lexeme
        declarator_ops = ()
    elif p._check_punct("("):
        p._advance()
        name, declarator_ops, _, top_pointer_is_qualified = p._parse_atomic_type_name_declarator(
            allow_abstract=True,
            allow_gnu_attributes=allow_gnu_attributes,
        )
        p._expect_punct(")")
    elif allow_abstract:
        name = None
        declarator_ops = ()
    else:
        raise p._expected_identifier_error()
    while True:
        if p._skip_type_name_attributes(allow_gnu_attributes=allow_gnu_attributes):
            continue
        if p._check_punct("["):
            p._advance()
            size_token = p._current()
            size_expr = p._parse_assignment()
            size = p._parse_array_size_expr(size_expr, size_token)
            p._expect_punct("]")
            declarator_ops = declarator_ops + (("arr", size),)
            continue
        if p._check_punct("("):
            p._advance()
            function_declarator = p._parse_function_suffix_params()
            p._expect_punct(")")
            declarator_ops = declarator_ops + (("fn", function_declarator),)
            continue
        break
    if not declarator_ops or declarator_ops[0][0] != "ptr":
        top_pointer_is_qualified = False
    return name, declarator_ops, top_pointer_is_qualified


def is_top_level_qualified_type_name(
    *,
    base_has_leading_qualifier: bool,
    base_is_qualified_typedef: bool,
    declarator_has_prefix_qualifier: bool,
    declarator_ops: tuple[DeclaratorOp, ...],
    top_pointer_is_qualified: bool,
) -> bool:
    if declarator_ops:
        if declarator_ops[0][0] == "ptr":
            return top_pointer_is_qualified
        return False
    return (
        base_has_leading_qualifier or base_is_qualified_typedef or declarator_has_prefix_qualifier
    )


def build_declarator_type(
    base_type: TypeSpec,
    declarator_ops: tuple[DeclaratorOp, ...],
) -> TypeSpec:
    combined_ops = declarator_ops + base_type.declarator_ops
    return TypeSpec(
        base_type.name,
        declarator_ops=combined_ops,
        qualifiers=base_type.qualifiers,
        is_atomic=base_type.is_atomic,
        atomic_target=base_type.atomic_target,
        enum_tag=base_type.enum_tag,
        enum_members=base_type.enum_members,
        record_tag=base_type.record_tag,
        record_members=base_type.record_members,
        typeof_expr=base_type.typeof_expr,
    )


def parse_declarator(
    parser: object,
    allow_abstract: bool,
    *,
    allow_vla: bool = False,
    allow_parameter_arrays: bool = False,
    allow_flexible_array: bool = False,
) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
    p = cast(Any, parser)
    p._skip_type_qualifiers()
    p._skip_calling_convention_identifiers_before_pointer()
    pointer_count = 0
    while p._check_punct("*"):
        p._advance()
        p._skip_type_qualifiers()
        p._skip_calling_convention_identifiers_after_pointer()
        pointer_count += 1
    name, ops = p._parse_direct_declarator(
        allow_abstract,
        allow_vla=allow_vla,
        allow_parameter_arrays=allow_parameter_arrays,
        allow_flexible_array=allow_flexible_array,
    )
    if pointer_count:
        ops = ops + (POINTER_OP,) * pointer_count
    return name, ops


def parse_direct_declarator(
    parser: object,
    allow_abstract: bool,
    *,
    allow_vla: bool = False,
    allow_parameter_arrays: bool = False,
    allow_flexible_array: bool = False,
) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
    p = cast(Any, parser)
    name: str | None
    ops: tuple[DeclaratorOp, ...]
    if p._current().kind == TokenKind.IDENT:
        token = p._advance()
        assert isinstance(token.lexeme, str)
        name = token.lexeme
        p._skip_decl_attributes()
        ops = ()
    elif p._check_punct("("):
        p._advance()
        name, ops = p._parse_declarator(
            allow_abstract=True,
            allow_vla=allow_vla,
            allow_parameter_arrays=allow_parameter_arrays,
            allow_flexible_array=allow_flexible_array,
        )
        p._expect_punct(")")
    elif allow_abstract:
        name = None
        ops = ()
    else:
        raise p._expected_identifier_error()
    while True:
        if p._check_punct("["):
            p._advance()
            array_decl = p._parse_array_declarator(
                allow_vla=allow_vla,
                allow_parameter_arrays=allow_parameter_arrays,
                allow_flexible_array=allow_flexible_array,
            )
            ops = ops + (("arr", array_decl),)
            continue
        if p._check_punct("("):
            p._advance()
            if p._capture_next_fn_params and name is not None:
                p._capture_next_fn_params = False
                params, has_prototype, is_variadic = p._parse_params()
                p._expect_punct(")")
                param_types = tuple(p.type_spec for p in params) if has_prototype else None
                p._function_def_info = (params, has_prototype, is_variadic)
                ops = ops + (("fn", (param_types, is_variadic)),)
            else:
                function_declarator = p._parse_function_suffix_params()
                p._expect_punct(")")
                ops = ops + (("fn", function_declarator),)
            continue
        break
    return name, ops


def parse_array_declarator(
    parser: object,
    *,
    allow_vla: bool,
    allow_parameter_arrays: bool,
    allow_flexible_array: bool = False,
) -> int | ArrayDecl:
    p = cast(Any, parser)
    qualifiers: list[str] = []
    seen_qualifiers: set[str] = set()
    has_static_bound = False
    while allow_parameter_arrays and p._current().kind == TokenKind.KEYWORD:
        lexeme = str(p._current().lexeme)
        if lexeme in TYPE_QUALIFIER_KEYWORDS:
            if lexeme in seen_qualifiers:
                raise ParserError(f"Duplicate type qualifier: '{lexeme}'", p._current())
            qualifiers.append(lexeme)
            seen_qualifiers.add(lexeme)
            p._advance()
            continue
        if lexeme == "static":
            if has_static_bound:
                raise ParserError("Duplicate array bound specifier: 'static'", p._current())
            has_static_bound = True
            p._advance()
            continue
        break
    size_expr: Expr | None = None
    size_token = p._current()
    if not p._check_punct("]"):
        size_expr = p._parse_assignment()
    p._expect_punct("]")
    if size_expr is None:
        if has_static_bound:
            raise ParserError("Array parameter with 'static' requires a size", size_token)
        if allow_parameter_arrays:
            return ArrayDecl(None, tuple(qualifiers), False)
        if allow_flexible_array:
            return ArrayDecl(None)
        if allow_vla:
            return ArrayDecl(None)
        raise ParserError("Array size is required in this context", size_token)
    if isinstance(size_expr, IntLiteral):
        if not isinstance(size_expr.value, str):
            raise ParserError("Array size literal token is malformed", size_token)
        message = _array_size_literal_error(size_expr.value)
        if message is not None:
            raise ParserError(message, size_token)
    size = p._eval_array_size_expr(size_expr)
    if size is not None and (size < 0 or (size == 0 and p._std == "c11")):
        raise ParserError("Array size must be positive", size_token)
    if allow_parameter_arrays and (qualifiers or has_static_bound):
        return ArrayDecl(size_expr, tuple(qualifiers), has_static_bound)
    if size is not None:
        return size
    if allow_vla:
        return ArrayDecl(size_expr, tuple(qualifiers), has_static_bound)
    raise ParserError(
        _array_size_non_ice_error(size_expr, p._eval_array_size_expr),
        size_token,
    )


def parse_function_suffix_params(parser: object) -> FunctionDeclarator:
    p = cast(Any, parser)
    if p._check_punct(")"):
        return None, False
    if p._check_keyword("void") and p._peek_punct(")"):
        p._advance()
        return (), False
    if p._check_punct("..."):
        raise ParserError("Expected parameter before ...", p._current())
    params = [p._parse_param().type_spec]
    is_variadic = False
    while p._check_punct(","):
        p._advance()
        if p._check_punct(")"):
            raise ParserError("Expected parameter declaration after ','", p._current())
        if p._check_punct("..."):
            p._advance()
            is_variadic = True
            if not p._check_punct(")"):
                if p._check_punct(","):
                    p._advance()
                raise ParserError(
                    "Expected ')' after ... in parameter list",
                    p._current(),
                )
            break
        params.append(p._parse_param().type_spec)
    return tuple(params), is_variadic


def parse_type_name(parser: object) -> TypeSpec:
    p = cast(Any, parser)
    base_type = p._parse_type_spec(context="type-name")
    name, declarator_ops = p._parse_declarator(allow_abstract=True, allow_vla=True)
    if name is not None:
        raise ParserError(
            f"Type name cannot declare identifier '{name}'",
            p._current(),
        )
    return p._build_declarator_type(base_type, declarator_ops)


def try_parse_type_name(parser: object) -> bool:
    p = cast(Any, parser)
    saved_index = p._index
    try:
        base_type = p._parse_type_spec()
        name, declarator_ops = p._parse_declarator(allow_abstract=True)
        if name is not None:
            p._index = saved_index
            return False
        p._build_declarator_type(base_type, declarator_ops)
        p._index = saved_index
        return True
    except ParserError:
        p._index = saved_index
        return False


def is_assignment_operator(token: Token, operators: tuple[str, ...]) -> bool:
    return token.kind == TokenKind.PUNCTUATOR and token.lexeme in operators
