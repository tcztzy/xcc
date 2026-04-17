from collections.abc import Callable

from xcc.ast import (
    AlignofExpr,
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
    UnaryExpr,
    UpdateExpr,
)

_INTEGER_LITERAL_SUFFIXES = {"", "u", "l", "ul", "lu", "ll", "ull", "llu"}


def _parse_int_literal_value(lexeme: str) -> int | None:
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = lexeme[suffix_start:].lower()
    if suffix not in _INTEGER_LITERAL_SUFFIXES:
        return None
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        return None if not digits else int(digits, 16)
    if body.startswith("0") and len(body) > 1:
        if any(ch not in "01234567" for ch in body):
            return None
        return int(body, 8)
    if not body.isdigit():
        return None
    return int(body)


def _array_size_literal_error(lexeme: str) -> str | None:
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = lexeme[suffix_start:].lower()
    if suffix not in _INTEGER_LITERAL_SUFFIXES:
        return "Array size literal has unsupported integer suffix"
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        if not digits:
            return "Array size hexadecimal literal requires at least one digit"
        return None
    if body.startswith("0") and len(body) > 1:
        if any(ch not in "01234567" for ch in body):
            return "Array size octal literal contains non-octal digits"
        return None
    if not body.isdigit():
        return "Array size literal must contain decimal digits"
    return None


def _array_size_non_ice_error(
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
            return _array_size_non_ice_error(expr.expr, eval_expr)
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
            return _array_size_non_ice_error(branch, eval_expr)
        return "Array size conditional expression is not an integer constant expression"
    return f"Array size expression '{type(expr).__name__}' is not an integer constant expression"
