from typing import Any, cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    BinaryExpr,
    CastExpr,
    ConditionalExpr,
    Expr,
    GenericExpr,
    Identifier,
    IntLiteral,
    SizeofExpr,
    StringLiteral,
    TypeSpec,
    UnaryExpr,
)
from xcc.lexer import Token

from .diagnostics import (
    _array_size_literal_error,
    _array_size_non_ice_error,
    _parse_int_literal_value,
)

_POINTER_OP = ("ptr", 0)
_POINTER_SIZE = 8
_BASE_TYPE_SIZES = {
    "_Bool": 1,
    "char": 1,
    "unsigned char": 1,
    "short": 2,
    "unsigned short": 2,
    "int": 4,
    "unsigned int": 4,
    "long": 8,
    "unsigned long": 8,
    "long long": 8,
    "unsigned long long": 8,
    "__int128_t": 16,
    "__uint128_t": 16,
    "float": 4,
    "double": 8,
    "long double": 16,
    "enum": 4,
    "_Float16": 2,
    "__fp16": 2,
    "_Float32": 4,
    "_Float64": 8,
    "_Float128": 16,
    "_Float32x": 8,
    "_Float64x": 16,
}


def parse_array_size(parser: object, token: Token) -> int:
    p = cast(Any, parser)
    lexeme = token.lexeme
    if not isinstance(lexeme, str):
        raise p._make_error("Array size literal token is malformed", token)
    message = _array_size_literal_error(lexeme)
    if message is not None:
        raise p._make_error(message, token)
    size = _parse_int_literal_value(lexeme)
    assert size is not None
    if size < 0 or (size == 0 and p._std == "c11"):
        raise p._make_error("Array size must be positive", token)
    return size


def parse_array_size_expr(parser: object, expr: Expr, token: Token) -> int:
    p = cast(Any, parser)
    size = p._eval_array_size_expr(expr)
    if size is None:
        raise p._make_error(_array_size_non_ice_error(expr, p._eval_array_size_expr), token)
    if size < 0 or (size == 0 and p._std == "c11"):
        raise p._make_error("Array size must be positive", token)
    return size


def parse_array_size_expr_or_vla(parser: object, expr: Expr, token: Token) -> int:
    p = cast(Any, parser)
    size = p._eval_array_size_expr(expr)
    if size is None:
        return -1
    if size < 0 or (size == 0 and p._std == "c11"):
        raise p._make_error("Array size must be positive", token)
    return size


def eval_array_size_expr(parser: object, expr: Expr) -> int | None:
    p = cast(Any, parser)
    if isinstance(expr, IntLiteral):
        assert isinstance(expr.value, str)
        return _parse_int_literal_value(expr.value)
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
        q, _ = divmod(abs(left), abs(right))
        return q if (left >= 0) == (right >= 0) else -q
    if op == "%":
        if right == 0:
            return None
        q, _ = divmod(abs(left), abs(right))
        if (left >= 0) != (right >= 0):
            q = -q
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


def eval_array_size_generic_expr(parser: object, expr: GenericExpr) -> int | None:
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


def array_size_generic_control_type(parser: object, control: Expr) -> TypeSpec | None:
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
    lowered = literal.lower()
    if lowered.endswith("ull") or lowered.endswith("llu"):
        return TypeSpec("unsigned long long")
    if lowered.endswith("ll"):
        return TypeSpec("long long")
    if lowered.endswith("ul") or lowered.endswith("lu") or lowered.endswith("u"):
        return TypeSpec("unsigned int")
    if lowered.endswith("l"):
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
        )
    if kind == "fn":
        return TypeSpec(type_spec.name, declarator_ops=(_POINTER_OP, *type_spec.declarator_ops))
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
    )


def sizeof_type_spec(parser: object, type_spec: TypeSpec) -> int | None:
    p = cast(Any, parser)

    def eval_ops(index: int) -> int | None:
        if index >= len(type_spec.declarator_ops):
            return _BASE_TYPE_SIZES.get(type_spec.name)
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
                    evaluated = p._eval_array_size_expr(value.length)
                    if evaluated is None:
                        return None
                    value = evaluated
            if value <= 0:
                return None
            item_size = eval_ops(index + 1)
            return None if item_size is None else item_size * value
        if kind == "ptr":
            return _POINTER_SIZE
        return None

    return eval_ops(0)


def alignof_type_spec(parser: object, type_spec: TypeSpec) -> int | None:
    p = cast(Any, parser)
    if not type_spec.declarator_ops:
        return _BASE_TYPE_SIZES.get(type_spec.name)
    kind, _ = type_spec.declarator_ops[0]
    if kind == "ptr":
        return _POINTER_SIZE
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
            )
        )
    return None
