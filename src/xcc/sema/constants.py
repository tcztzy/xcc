from xcc.ast import (
    AlignofExpr,
    BinaryExpr,
    BuiltinOffsetofExpr,
    CastExpr,
    CharLiteral,
    ConditionalExpr,
    Expr,
    GenericExpr,
    Identifier,
    InitList,
    IntLiteral,
    MemberExpr,
    SizeofExpr,
    SubscriptExpr,
    UnaryExpr,
)
from xcc.types import (
    INT,
    LLONG,
    LONG,
    UINT,
    ULLONG,
    ULONG,
    Type,
)

from .symbols import EnumConstSymbol, Scope, VarSymbol
from .type_helpers import SIGNED_INTEGER_TYPE_LIMITS, UNSIGNED_INTEGER_TYPE_LIMITS

HEX_DIGITS = "0123456789abcdefABCDEF"
OCTAL_DIGITS = "01234567"
SIMPLE_ESCAPES = {
    "'": ord("'"),
    '"': ord('"'),
    "?": ord("?"),
    "\\": ord("\\"),
    "a": 7,
    "b": 8,
    "f": 12,
    "n": 10,
    "r": 13,
    "t": 9,
    "v": 11,
}
DECIMAL_LITERAL_CANDIDATES: dict[str, tuple[Type, ...]] = {
    "": (INT, LONG, LLONG),
    "u": (UINT, ULONG, ULLONG),
    "l": (LONG, LLONG),
    "ul": (ULONG, ULLONG),
    "lu": (ULONG, ULLONG),
    "ll": (LLONG,),
    "ull": (ULLONG,),
    "llu": (ULLONG,),
}
NON_DECIMAL_LITERAL_CANDIDATES: dict[str, tuple[Type, ...]] = {
    "": (INT, UINT, LONG, ULONG, LLONG, ULLONG),
    "u": (UINT, ULONG, ULLONG),
    "l": (LONG, ULONG, LLONG, ULLONG),
    "ul": (ULONG, ULLONG),
    "lu": (ULONG, ULLONG),
    "ll": (LLONG, ULLONG),
    "ull": (ULLONG,),
    "llu": (ULLONG,),
}


def parse_int_literal(analyzer: object, lexeme: str | int) -> tuple[int, Type] | None:
    if isinstance(lexeme, int):
        return lexeme, INT
    if not isinstance(lexeme, str):
        return None
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = lexeme[suffix_start:].lower()
    is_decimal = True
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        if not digits:
            return None
        value = int(digits, 16)
        is_decimal = False
    elif body.startswith("0") and len(body) > 1:
        if any(ch not in "01234567" for ch in body):
            return None
        value = int(body, 8)
        is_decimal = False
    elif body.isdigit():
        value = int(body)
    else:
        return None
    candidates = (DECIMAL_LITERAL_CANDIDATES if is_decimal else NON_DECIMAL_LITERAL_CANDIDATES).get(
        suffix
    )
    if candidates is None:
        return None
    for candidate_type in candidates:
        if analyzer._fits_integer_literal_value(value, candidate_type):  # type: ignore[attr-defined]
            return value, candidate_type
    return None


def fits_integer_literal_value(value: int, type_: Type) -> bool:
    signed_bounds = SIGNED_INTEGER_TYPE_LIMITS.get(type_)
    if signed_bounds is not None:
        return signed_bounds[0] <= value <= signed_bounds[1]
    unsigned_max = UNSIGNED_INTEGER_TYPE_LIMITS.get(type_)
    return unsigned_max is not None and 0 <= value <= unsigned_max


def eval_int_constant_expr(analyzer: object, expr: Expr, scope: Scope) -> int | None:
    if isinstance(expr, IntLiteral):
        parsed = analyzer._parse_int_literal(expr.value)  # type: ignore[attr-defined]
        return None if parsed is None else parsed[0]
    if isinstance(expr, CharLiteral):
        return analyzer._char_const_value(expr.value)  # type: ignore[attr-defined]
    if isinstance(expr, UnaryExpr) and expr.op in {"+", "-", "!", "~"}:
        operand_value = analyzer._eval_int_constant_expr(expr.operand, scope)  # type: ignore[attr-defined]
        if operand_value is None:
            return None
        if expr.op == "+":
            return operand_value
        if expr.op == "-":
            return -operand_value
        if expr.op == "!":
            return 0 if operand_value else 1
        return ~operand_value
    if isinstance(expr, BinaryExpr):
        return _eval_binary_int_constant_expr(analyzer, expr, scope)
    if isinstance(expr, ConditionalExpr):
        condition_value = analyzer._eval_int_constant_expr(expr.condition, scope)  # type: ignore[attr-defined]
        if condition_value is None:
            return None
        branch = expr.then_expr if condition_value else expr.else_expr
        return analyzer._eval_int_constant_expr(branch, scope)  # type: ignore[attr-defined]
    if isinstance(expr, CastExpr):
        if not analyzer._is_integer_type(analyzer._resolve_type(expr.type_spec)):  # type: ignore[attr-defined]
            return None
        return analyzer._eval_int_constant_expr(expr.expr, scope)  # type: ignore[attr-defined]
    if isinstance(expr, SizeofExpr):
        if expr.type_spec is not None:
            analyzer._register_type_spec(expr.type_spec)  # type: ignore[attr-defined]
            if analyzer._is_invalid_sizeof_type_spec(expr.type_spec):  # type: ignore[attr-defined]
                return None
            return analyzer._sizeof_type(analyzer._resolve_type(expr.type_spec))  # type: ignore[attr-defined]
        if expr.expr is not None:
            operand_type = analyzer._type_map.get(expr.expr)  # type: ignore[attr-defined]
            if operand_type is not None:
                return analyzer._sizeof_type(operand_type)  # type: ignore[attr-defined]
        return None
    if isinstance(expr, AlignofExpr):
        if expr.type_spec is None:
            return None
        analyzer._register_type_spec(expr.type_spec)  # type: ignore[attr-defined]
        if analyzer._is_invalid_alignof_type_spec(expr.type_spec):  # type: ignore[attr-defined]
            return None
        return analyzer._alignof_type(analyzer._resolve_type(expr.type_spec))  # type: ignore[attr-defined]
    if isinstance(expr, BuiltinOffsetofExpr):
        return None
    if isinstance(expr, GenericExpr):
        return _eval_generic_int_constant_expr(analyzer, expr, scope)
    if isinstance(expr, Identifier):
        symbol = scope.lookup(expr.name)
        if isinstance(symbol, EnumConstSymbol):
            return symbol.value
        if isinstance(symbol, VarSymbol) and symbol.constant_value is not None:
            if getattr(analyzer, "_allow_const_var_folding", False):  # type: ignore[attr-defined]
                return symbol.constant_value
    if isinstance(expr, SubscriptExpr):
        if not getattr(analyzer, "_allow_const_var_folding", False):  # type: ignore[attr-defined]
            return None
        index = analyzer._eval_int_constant_expr(expr.index, scope)  # type: ignore[attr-defined]
        if index is None:
            return None
        if isinstance(expr.base, Identifier):
            symbol = scope.lookup(expr.base.name)
            if isinstance(symbol, VarSymbol) and symbol._init_expr is not None:
                init_list = symbol._init_expr
                if isinstance(init_list, InitList) and 0 <= index < len(init_list.items):
                    item = init_list.items[index]
                    if item.designators:
                        return None
                    init_val = item.initializer
                    if isinstance(init_val, InitList):
                        return None
                    return analyzer._eval_int_constant_expr(init_val, scope)  # type: ignore[attr-defined]
    if isinstance(expr, MemberExpr):
        if not getattr(analyzer, "_allow_const_var_folding", False):  # type: ignore[attr-defined]
            return None
        return _eval_member_expr(analyzer, expr, scope)
    return None


def _eval_member_expr(analyzer: object, expr: "MemberExpr", scope: Scope) -> int | None:
    """Evaluate a member access expression in a const context."""
    # Evaluate the base expression first
    base_val = analyzer._eval_int_constant_expr(expr.base, scope)  # type: ignore[attr-defined]
    if base_val is not None:
        # If base is a scalar, the member access resolves to that scalar
        # (scalar initializes struct's first member recursively).
        return base_val
    # If base is an Identifier, resolve the member through the init_list.
    from xcc.sema.symbols import VarSymbol as _VarSymbol

    if isinstance(expr.base, Identifier):
        symbol = scope.lookup(expr.base.name)
        if isinstance(symbol, _VarSymbol) and symbol._init_expr is not None:
            base_type = symbol.type_
            if isinstance(symbol._init_expr, InitList):
                return _lookup_member_in_init(
                    analyzer, symbol._init_expr, base_type, expr.member, scope
                )
    return None


def _lookup_member_in_init(
    analyzer: object,
    init_list: "InitList",
    base_type: object,
    member_name: str,
    scope: Scope,
) -> int | None:
    """Find a member's initializer value in an InitList."""
    if not analyzer._is_record_name(base_type.name):  # type: ignore[attr-defined]
        return None
    members = analyzer._record_members(base_type.name)  # type: ignore[attr-defined]
    if members is None:
        return None
    for idx, m in enumerate(members):
        if m.name == member_name:
            if idx < len(init_list.items):
                item = init_list.items[idx]
                if item.designators:
                    return None
                return analyzer._eval_int_constant_expr(item.initializer, scope)  # type: ignore[attr-defined]
    return None


def _eval_binary_int_constant_expr(
    analyzer: object,
    expr: BinaryExpr,
    scope: Scope,
) -> int | None:
    left_value = analyzer._eval_int_constant_expr(expr.left, scope)  # type: ignore[attr-defined]
    if left_value is None:
        return None
    if expr.op == "&&":
        if not left_value:
            return 0
        right_value = analyzer._eval_int_constant_expr(expr.right, scope)  # type: ignore[attr-defined]
        if right_value is None:
            return None
        return 1 if right_value else 0
    if expr.op == "||":
        if left_value:
            return 1
        right_value = analyzer._eval_int_constant_expr(expr.right, scope)  # type: ignore[attr-defined]
        if right_value is None:
            return None
        return 1 if right_value else 0
    right_value = analyzer._eval_int_constant_expr(expr.right, scope)  # type: ignore[attr-defined]
    if right_value is None:
        return None
    if expr.op == "+":
        return left_value + right_value
    if expr.op == "-":
        return left_value - right_value
    if expr.op == "*":
        return left_value * right_value
    if expr.op == "/":
        if right_value == 0:
            return None
        return left_value // right_value
    if expr.op == "%":
        if right_value == 0:
            return None
        return left_value % right_value
    if expr.op == "<<":
        if right_value < 0:
            return None
        return left_value << right_value
    if expr.op == ">>":
        if right_value < 0:
            return None
        return left_value >> right_value
    if expr.op == "<":
        return 1 if left_value < right_value else 0
    if expr.op == "<=":
        return 1 if left_value <= right_value else 0
    if expr.op == ">":
        return 1 if left_value > right_value else 0
    if expr.op == ">=":
        return 1 if left_value >= right_value else 0
    if expr.op == "==":
        return 1 if left_value == right_value else 0
    if expr.op == "!=":
        return 1 if left_value != right_value else 0
    if expr.op == "&":
        return left_value & right_value
    if expr.op == "^":
        return left_value ^ right_value
    if expr.op == "|":
        return left_value | right_value
    return None


def _eval_generic_int_constant_expr(
    analyzer: object,
    expr: GenericExpr,
    scope: Scope,
) -> int | None:
    selected_expr: Expr | None = None
    default_expr: Expr | None = None
    control_type = analyzer._type_map.get(expr.control)  # type: ignore[attr-defined]
    if control_type is None:
        control_type = analyzer._analyze_expr(expr.control, scope)  # type: ignore[attr-defined]
    control_type = analyzer._decay_array_value(control_type)  # type: ignore[attr-defined]
    for assoc_type_spec, assoc_expr in expr.associations:
        if assoc_type_spec is None:
            default_expr = assoc_expr
            continue
        analyzer._register_type_spec(assoc_type_spec)  # type: ignore[attr-defined]
        if analyzer._resolve_type(assoc_type_spec) == control_type:  # type: ignore[attr-defined]
            selected_expr = assoc_expr
    if selected_expr is None:
        selected_expr = default_expr
    if selected_expr is None:
        return None
    return analyzer._eval_int_constant_expr(selected_expr, scope)  # type: ignore[attr-defined]


def char_const_value(analyzer: object, lexeme: str) -> int | None:
    body = analyzer._char_literal_body(lexeme)  # type: ignore[attr-defined]
    if body is None:
        return None
    units = analyzer._decode_escaped_units(body)  # type: ignore[attr-defined]
    if len(units) != 1:
        return None
    return units[0]


def char_literal_body(lexeme: str) -> str | None:
    prefixless = lexeme
    if lexeme[:1] in {"u", "U", "L"}:
        prefixless = lexeme[1:]
    if not prefixless.startswith("'") or not prefixless.endswith("'"):
        return None
    return prefixless[1:-1]


def string_literal_required_length(analyzer: object, lexeme: str) -> int | None:
    body = analyzer._string_literal_body(lexeme)  # type: ignore[attr-defined]
    return None if body is None else len(analyzer._decode_escaped_units(body)) + 1  # type: ignore[attr-defined]


def string_literal_body(lexeme: str) -> str | None:
    if lexeme.startswith('"') and lexeme.endswith('"'):
        return lexeme[1:-1]
    if lexeme.startswith('u8"') and lexeme.endswith('"'):
        return lexeme[3:-1]
    return None


def decode_escaped_units(body: str) -> list[int]:
    units: list[int] = []
    index = 0
    while index < len(body):
        ch = body[index]
        if ch != "\\":
            units.append(ord(ch))
            index += 1
            continue
        index += 1
        esc = body[index]
        simple = SIMPLE_ESCAPES.get(esc)
        if simple is not None:
            units.append(simple)
            index += 1
            continue
        if esc == "x":
            index += 1
            start = index
            while index < len(body) and body[index] in HEX_DIGITS:
                index += 1
            units.append(int(body[start:index], 16))
            continue
        if esc in OCTAL_DIGITS:
            start = index
            index += 1
            if index < len(body) and body[index] in OCTAL_DIGITS:
                index += 1
            if index < len(body) and body[index] in OCTAL_DIGITS:
                index += 1
            units.append(int(body[start:index], 8))
            continue
        width = 4 if esc == "u" else 8
        index += 1
        units.append(int(body[index : index + width], 16))
        index += width
    return units
