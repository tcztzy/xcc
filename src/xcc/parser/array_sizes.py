from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
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
from xcc.lexer import Token

if TYPE_CHECKING:
    from . import Parser

_POINTER_OP = ("ptr", 0)
_INTEGER_LITERAL_SUFFIXES = {"", "u", "l", "ul", "lu", "ll", "ull", "llu"}


def parse_int_literal_value(lexeme: str) -> int | None:
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = _normalized_integer_suffix(lexeme, suffix_start)
    if suffix is None:
        return None
    if suffix not in _INTEGER_LITERAL_SUFFIXES:
        return None
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        return None if not digits else int(digits, 16)
    if body.startswith("0") and len(body) > 1:
        has_non_octal_digit = False
        for ch in body:
            if ch not in "01234567":
                has_non_octal_digit = True
                break
        if has_non_octal_digit:
            return None
        return int(body, 8)
    if not body.isdigit():
        return None
    return int(body)


def _normalized_integer_suffix(lexeme: str, suffix_start: int) -> str | None:
    suffix = ""
    index = suffix_start
    while index < len(lexeme):
        ch = lexeme[index]
        if ch in "uU":
            suffix += "u"
        elif ch in "lL":
            suffix += "l"
        else:
            return None
        index += 1
    return suffix


def array_size_literal_error(lexeme: str) -> str | None:
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = _normalized_integer_suffix(lexeme, suffix_start)
    if suffix is None:
        return "Array size literal has unsupported integer suffix"
    if suffix not in _INTEGER_LITERAL_SUFFIXES:
        return "Array size literal has unsupported integer suffix"
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        if not digits:
            return "Array size hexadecimal literal requires at least one digit"
        return None
    if body.startswith("0") and len(body) > 1:
        has_non_octal_digit = False
        for ch in body:
            if ch not in "01234567":
                has_non_octal_digit = True
                break
        if has_non_octal_digit:
            return "Array size octal literal contains non-octal digits"
        return None
    if not body.isdigit():
        return "Array size literal must contain decimal digits"
    return None


def array_size_non_ice_error(
    expr: Expr,
    eval_expr: Callable[[Expr], int | None],
) -> str:
    if isinstance(expr, Identifier):
        return f"Array size identifier '{expr.name}' is not an integer constant expression"
    if isinstance(expr, UnaryExpr):
        return f"Array size unary operator '{expr.op}' is not an integer constant expression"
    if isinstance(expr, BinaryExpr):
        return f"Array size binary operator '{expr.op}' is not an integer constant expression"
    if isinstance(expr, CallExpr):
        return "Array size call expression is not an integer constant expression"
    if isinstance(expr, GenericExpr):
        return "Array size generic selection is not an integer constant expression"
    if isinstance(expr, CommaExpr):
        return "Array size comma expression is not an integer constant expression"
    if isinstance(expr, AssignExpr):
        return "Array size assignment expression is not an integer constant expression"
    if isinstance(expr, UpdateExpr):
        return "Array size update expression is not an integer constant expression"
    if isinstance(expr, SubscriptExpr):
        return "Array size subscript expression is not an integer constant expression"
    if isinstance(expr, MemberExpr):
        return "Array size member access expression is not an integer constant expression"
    if isinstance(expr, CompoundLiteralExpr):
        return "Array size compound literal is not an integer constant expression"
    if isinstance(expr, IntLiteral):
        return "Array size integer literal is not an integer constant expression"
    if isinstance(expr, FloatLiteral):
        return "Array size floating literal is not an integer constant expression"
    if isinstance(expr, CharLiteral):
        return "Array size character literal is not an integer constant expression"
    if isinstance(expr, StringLiteral):
        return "Array size string literal is not an integer constant expression"
    if isinstance(expr, StatementExpr):
        return "Array size statement expression is not an integer constant expression"
    if isinstance(expr, LabelAddressExpr):
        return "Array size label address expression is not an integer constant expression"
    if isinstance(expr, CastExpr):
        if eval_expr(expr.expr) is None:
            return array_size_non_ice_error(expr.expr, eval_expr)
        return "Array size cast expression is not an integer constant expression"
    if isinstance(expr, SizeofExpr):
        return "Array size sizeof expression is not an integer constant expression"
    if isinstance(expr, AlignofExpr):
        return "Array size alignof expression is not an integer constant expression"
    if isinstance(expr, ConditionalExpr):
        if eval_expr(expr.condition) is None:
            return "Array size conditional condition is not an integer constant expression"
        branch = expr.then_expr if eval_expr(expr.condition) != 0 else expr.else_expr
        if eval_expr(branch) is None:
            return array_size_non_ice_error(branch, eval_expr)
        return "Array size conditional expression is not an integer constant expression"
    return f"Array size expression '{type(expr).__name__}' is not an integer constant expression"


def array_size_non_ice_error_for_parser(parser: "Parser", expr: Expr) -> str:
    if isinstance(expr, Identifier):
        return f"Array size identifier '{expr.name}' is not an integer constant expression"
    if isinstance(expr, UnaryExpr):
        return f"Array size unary operator '{expr.op}' is not an integer constant expression"
    if isinstance(expr, BinaryExpr):
        return f"Array size binary operator '{expr.op}' is not an integer constant expression"
    if isinstance(expr, CallExpr):
        return "Array size call expression is not an integer constant expression"
    if isinstance(expr, GenericExpr):
        return "Array size generic selection is not an integer constant expression"
    if isinstance(expr, CommaExpr):
        return "Array size comma expression is not an integer constant expression"
    if isinstance(expr, AssignExpr):
        return "Array size assignment expression is not an integer constant expression"
    if isinstance(expr, UpdateExpr):
        return "Array size update expression is not an integer constant expression"
    if isinstance(expr, SubscriptExpr):
        return "Array size subscript expression is not an integer constant expression"
    if isinstance(expr, MemberExpr):
        return "Array size member access expression is not an integer constant expression"
    if isinstance(expr, CompoundLiteralExpr):
        return "Array size compound literal is not an integer constant expression"
    if isinstance(expr, IntLiteral):
        return "Array size integer literal is not an integer constant expression"
    if isinstance(expr, FloatLiteral):
        return "Array size floating literal is not an integer constant expression"
    if isinstance(expr, CharLiteral):
        return "Array size character literal is not an integer constant expression"
    if isinstance(expr, StringLiteral):
        return "Array size string literal is not an integer constant expression"
    if isinstance(expr, StatementExpr):
        return "Array size statement expression is not an integer constant expression"
    if isinstance(expr, LabelAddressExpr):
        return "Array size label address expression is not an integer constant expression"
    if isinstance(expr, CastExpr):
        if parser._eval_array_size_expr(expr.expr) is None:
            return array_size_non_ice_error_for_parser(parser, expr.expr)
        return "Array size cast expression is not an integer constant expression"
    if isinstance(expr, SizeofExpr):
        return "Array size sizeof expression is not an integer constant expression"
    if isinstance(expr, AlignofExpr):
        return "Array size alignof expression is not an integer constant expression"
    if isinstance(expr, ConditionalExpr):
        condition = parser._eval_array_size_expr(expr.condition)
        if condition is None:
            return "Array size conditional condition is not an integer constant expression"
        branch = expr.then_expr if condition != 0 else expr.else_expr
        if parser._eval_array_size_expr(branch) is None:
            return array_size_non_ice_error_for_parser(parser, branch)
        return "Array size conditional expression is not an integer constant expression"
    return "Array size expression is not an integer constant expression"


def parse_array_size(parser: "Parser", token: Token) -> int:
    p = cast(Any, parser)
    lexeme = token.lexeme
    if not isinstance(lexeme, str):
        raise p._make_error("Array size literal token is malformed", token)
    message = array_size_literal_error(lexeme)
    if message is not None:
        raise p._make_error(message, token)
    size = parse_int_literal_value(lexeme)
    assert size is not None
    if size < 0:
        raise p._make_error("Array size must be positive", token)
    return size


def parse_array_size_expr(parser: "Parser", expr: Expr, token: Token) -> int:
    p = cast(Any, parser)
    size = p._eval_array_size_expr(expr)
    if size is None:
        raise p._make_error(array_size_non_ice_error_for_parser(parser, expr), token)
    if size < 0:
        raise p._make_error("Array size must be positive", token)
    return size


def parse_array_size_expr_or_vla(parser: "Parser", expr: Expr, token: Token) -> int:
    p = cast(Any, parser)
    size = p._eval_array_size_expr(expr)
    if size is None:
        return -1
    if size < 0:
        raise p._make_error("Array size must be positive", token)
    return size


def eval_array_size_expr(parser: "Parser", expr: Expr) -> int | None:
    p = cast(Any, parser)
    if isinstance(expr, IntLiteral):
        assert isinstance(expr.value, str)
        return parse_int_literal_value(expr.value)
    if isinstance(expr, Identifier):
        return p._lookup_ordinary_constant(expr.name)
    if isinstance(expr, GenericExpr):
        return p._eval_array_size_generic_expr(expr)
    if isinstance(expr, CastExpr):
        return p._eval_array_size_expr(expr.expr)
    if isinstance(expr, SizeofExpr):
        if expr.type_spec is not None:
            return p._sizeof_type_spec(expr.type_spec)
        return None
    if isinstance(expr, AlignofExpr):
        if expr.type_spec is not None:
            return p._alignof_type_spec(expr.type_spec)
        return None
    if isinstance(expr, UnaryExpr) and expr.op in {"+", "-", "~", "!"}:
        operand = p._eval_array_size_expr(expr.operand)
        if operand is None:
            return None
        if expr.op == "+":
            return operand
        if expr.op == "-":
            return -operand
        if expr.op == "~":
            return ~operand
        return int(not operand)
    if isinstance(expr, BinaryExpr):
        left = p._eval_array_size_expr(expr.left)
        right = p._eval_array_size_expr(expr.right)
        if left is None or right is None:
            return None
        return _eval_array_size_binary_expr(expr.op, left, right)
    if isinstance(expr, ConditionalExpr):
        condition = p._eval_array_size_expr(expr.condition)
        if condition is None:
            return None
        branch = expr.then_expr if condition != 0 else expr.else_expr
        return p._eval_array_size_expr(branch)
    return None


def _eval_array_size_binary_expr(op: str, left: int, right: int) -> int | None:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            return None
        return _trunc_div_quotient(left, right)
    if op == "%":
        if right == 0:
            return None
        q = _trunc_div_quotient(left, right)
        return left - q * right
    if op == "<<":
        return None if right < 0 else left << right
    if op == ">>":
        return None if right < 0 else left >> right
    if op == "<":
        return int(left < right)
    if op == ">":
        return int(left > right)
    if op == "<=":
        return int(left <= right)
    if op == ">=":
        return int(left >= right)
    if op == "==":
        return int(left == right)
    if op == "!=":
        return int(left != right)
    if op == "&":
        return left & right
    if op == "^":
        return left ^ right
    if op == "|":
        return left | right
    if op == "&&":
        return int(bool(left) and bool(right))
    if op == "||":
        return int(bool(left) or bool(right))
    return None


def _trunc_div_quotient(left: int, right: int) -> int:
    left_abs = left
    if left_abs < 0:
        left_abs = -left_abs
    right_abs = right
    if right_abs < 0:
        right_abs = -right_abs
    quotient = left_abs // right_abs
    return quotient if (left >= 0) == (right >= 0) else -quotient


def eval_array_size_generic_expr(parser: "Parser", expr: GenericExpr) -> int | None:
    p = cast(Any, parser)
    control_type = p._array_size_generic_control_type(expr.control)
    default_expr: Expr | None = None
    selected_expr: Expr | None = None
    for assoc_type, assoc_expr in expr.associations:
        if assoc_type is None:
            default_expr = assoc_expr
            continue
        if control_type is not None and p._is_generic_control_type_compatible(
            control_type,
            assoc_type,
        ):
            selected_expr = assoc_expr
            break
    if selected_expr is None:
        selected_expr = default_expr
    if selected_expr is None:
        return None
    return p._eval_array_size_expr(selected_expr)


def array_size_generic_control_type(parser: "Parser", control: Expr) -> TypeSpec | None:
    p = cast(Any, parser)
    if isinstance(control, IntLiteral):
        return p._int_literal_type_spec(control.value)
    if isinstance(control, StringLiteral):
        return TypeSpec("char", declarator_ops=(_POINTER_OP,))
    if isinstance(control, Identifier):
        type_spec = p._lookup_ordinary_type(control.name)
        if type_spec is None:
            return None
        return p._decay_type_spec(type_spec)
    return None


def int_literal_type_spec(literal: str) -> TypeSpec:
    suffix_start = len(literal)
    while suffix_start > 0 and literal[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    suffix = _normalized_integer_suffix(literal, suffix_start)
    if suffix is None:
        suffix = ""
    if suffix == "ull" or suffix == "llu":
        return TypeSpec("unsigned long long")
    if suffix == "ll":
        return TypeSpec("long long")
    if suffix == "ul" or suffix == "lu" or suffix == "u":
        return TypeSpec("unsigned int")
    if suffix == "l":
        return TypeSpec("long")
    return TypeSpec("int")


def decay_type_spec(type_spec: TypeSpec) -> TypeSpec:
    if not type_spec.declarator_ops:
        return type_spec
    kind, _ = type_spec.declarator_ops[0]
    if kind == "arr":
        return TypeSpec(
            type_spec.name,
            declarator_ops=(_POINTER_OP, *type_spec.declarator_ops[1:]),
            qualifiers=type_spec.qualifiers,
            is_atomic=type_spec.is_atomic,
            atomic_target=type_spec.atomic_target,
            enum_tag=type_spec.enum_tag,
            enum_members=type_spec.enum_members,
            record_tag=type_spec.record_tag,
            record_members=type_spec.record_members,
            has_record_body=type_spec.has_record_body,
            typeof_expr=type_spec.typeof_expr,
        )
    if kind == "fn":
        return TypeSpec(
            type_spec.name,
            declarator_ops=(_POINTER_OP, *type_spec.declarator_ops),
            qualifiers=type_spec.qualifiers,
            is_atomic=type_spec.is_atomic,
            atomic_target=type_spec.atomic_target,
            enum_tag=type_spec.enum_tag,
            enum_members=type_spec.enum_members,
            record_tag=type_spec.record_tag,
            record_members=type_spec.record_members,
            has_record_body=type_spec.has_record_body,
            typeof_expr=type_spec.typeof_expr,
        )
    return type_spec


def is_generic_control_type_compatible(control_type: TypeSpec, assoc_type: TypeSpec) -> bool:
    return unqualified_type_spec(decay_type_spec(control_type)) == unqualified_type_spec(
        decay_type_spec(assoc_type)
    )


def unqualified_type_spec(type_spec: TypeSpec) -> TypeSpec:
    if not type_spec.qualifiers:
        return type_spec
    return TypeSpec(
        type_spec.name,
        declarator_ops=type_spec.declarator_ops,
        is_atomic=type_spec.is_atomic,
        atomic_target=type_spec.atomic_target,
        enum_tag=type_spec.enum_tag,
        enum_members=type_spec.enum_members,
        record_tag=type_spec.record_tag,
        record_members=type_spec.record_members,
        has_record_body=type_spec.has_record_body,
        typeof_expr=type_spec.typeof_expr,
    )


def sizeof_type_spec(parser: "Parser", type_spec: TypeSpec) -> int | None:
    return _sizeof_type_spec_from_index(parser, type_spec, 0)


def _sizeof_type_spec_from_index(
    parser: "Parser",
    type_spec: TypeSpec,
    index: int,
) -> int | None:
    if index >= len(type_spec.declarator_ops):
        return parser._data_layout.scalar_size(type_spec.name)
    kind, value = type_spec.declarator_ops[index]
    if kind == "arr":
        if not isinstance(value, int):
            if not isinstance(value, ArrayDecl):
                return None
            if value.length is None:
                return None
            if isinstance(value.length, int):
                value = value.length
            else:
                evaluated = parser._eval_array_size_expr(value.length)
                if evaluated is None:
                    return None
                value = evaluated
        if value <= 0:
            return None
        item_size = _sizeof_type_spec_from_index(parser, type_spec, index + 1)
        return None if item_size is None else item_size * value
    if kind == "ptr":
        return parser._data_layout.pointer_size
    return None


def alignof_type_spec(parser: "Parser", type_spec: TypeSpec) -> int | None:
    p = cast(Any, parser)
    if not type_spec.declarator_ops:
        if type_spec.record_tag is not None or type_spec.enum_tag is not None:
            return 16  # Conservative: actual alignment computed at codegen
        return p._data_layout.scalar_alignment(type_spec.name)
    kind, _ = type_spec.declarator_ops[0]
    if kind == "ptr":
        return p._data_layout.pointer_alignment
    if kind == "arr":
        return p._alignof_type_spec(
            TypeSpec(
                type_spec.name,
                declarator_ops=type_spec.declarator_ops[1:],
                is_atomic=type_spec.is_atomic,
                atomic_target=type_spec.atomic_target,
                enum_tag=type_spec.enum_tag,
                enum_members=type_spec.enum_members,
                record_tag=type_spec.record_tag,
                record_members=type_spec.record_members,
                has_record_body=type_spec.has_record_body,
                typeof_expr=type_spec.typeof_expr,
            )
        )
    return None
