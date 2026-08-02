from typing import TYPE_CHECKING

from xcc.ast import (
    AlignofExpr,
    BinaryExpr,
    BuiltinOffsetofExpr,
    BuiltinTypesCompatExpr,
    CastExpr,
    CharLiteral,
    CommaExpr,
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
    EVM_ADDRESS,
    EVM_UINT256,
    INT,
    INT128,
    LLONG,
    LONG,
    UINT,
    UINT128,
    ULLONG,
    ULONG,
    Type,
)

from .symbols import EnumConstSymbol, Scope, SemaError, VarSymbol

if TYPE_CHECKING:
    from . import Analyzer

HEX_DIGITS = "0123456789abcdefABCDEF"
OCTAL_DIGITS = "01234567"
SIMPLE_ESCAPES: dict[str, int] = {
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


def _allows_const_var_folding(analyzer: "Analyzer") -> bool:
    return analyzer._allow_const_var_folding


def parse_int_literal(analyzer: "Analyzer", lexeme: str) -> tuple[int, Type] | None:
    if not isinstance(lexeme, str):
        return None
    lexeme_text = lexeme
    suffix_start = len(lexeme_text)
    while suffix_start > 0 and lexeme_text[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme_text[:suffix_start]
    suffix = _normalized_integer_suffix(lexeme_text, suffix_start)
    if suffix is None:
        return None
    is_decimal = True
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        if not digits:
            return None
        value = int(digits, 16)
        is_decimal = False
    elif body.startswith("0") and len(body) > 1:
        has_non_octal_digit = False
        for ch in body:
            if ch not in "01234567":
                has_non_octal_digit = True
                break
        if has_non_octal_digit:
            return None
        value = int(body, 8)
        is_decimal = False
    elif body.isdigit():
        value = int(body, 10)
    else:
        return None
    candidates = _integer_literal_candidates(is_decimal, suffix)
    if candidates is None:
        return None
    for candidate_type in candidates:
        if analyzer._fits_integer_literal_value(value, candidate_type):
            return value, candidate_type
    return None


def _integer_literal_candidates(is_decimal: bool, suffix: str) -> tuple[Type, ...] | None:
    if is_decimal:
        if suffix == "":
            return (INT, LONG, LLONG)
        if suffix == "u":
            return (UINT, ULONG, ULLONG)
        if suffix == "l":
            return (LONG, LLONG)
        if suffix == "ul" or suffix == "lu":
            return (ULONG, ULLONG)
        if suffix == "ll":
            return (LLONG,)
        if suffix == "ull" or suffix == "llu":
            return (ULLONG,)
        return None
    if suffix == "":
        return (INT, UINT, LONG, ULONG, LLONG, ULLONG)
    if suffix == "u":
        return (UINT, ULONG, ULLONG)
    if suffix == "l":
        return (LONG, ULONG, LLONG, ULLONG)
    if suffix == "ul" or suffix == "lu":
        return (ULONG, ULLONG)
    if suffix == "ll":
        return (LLONG, ULLONG)
    if suffix == "ull" or suffix == "llu":
        return (ULLONG,)
    return None


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


def fits_integer_literal_value(value: int, type_: Type) -> bool:
    if type_ == INT:
        return -(1 << 31) <= value <= (1 << 31) - 1
    if type_ == LONG:
        return -(1 << 63) <= value <= (1 << 63) - 1
    if type_ == LLONG:
        return -(1 << 63) <= value <= (1 << 63) - 1
    if type_ == INT128:
        return -(1 << 127) <= value <= (1 << 127) - 1
    if type_ == UINT:
        return 0 <= value <= (1 << 32) - 1
    if type_ == ULONG:
        return 0 <= value <= (1 << 64) - 1
    if type_ == ULLONG:
        return 0 <= value <= (1 << 64) - 1
    if type_ == UINT128:
        return 0 <= value <= (1 << 128) - 1
    if type_ == EVM_ADDRESS:
        return 0 <= value <= (1 << 160) - 1
    if type_ == EVM_UINT256:
        return 0 <= value <= (1 << 256) - 1
    return False


def eval_int_constant_expr(analyzer: "Analyzer", expr: Expr, scope: Scope) -> int | None:
    if isinstance(expr, IntLiteral):
        parsed = analyzer._parse_int_literal(expr.value)
        return None if parsed is None else parsed[0]
    if isinstance(expr, CharLiteral):
        return analyzer._char_const_value(expr.value)
    if isinstance(expr, UnaryExpr) and expr.op in {"+", "-", "!", "~"}:
        operand_value = analyzer._eval_int_constant_expr(expr.operand, scope)
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
        condition_value = analyzer._eval_int_constant_expr(expr.condition, scope)
        if condition_value is None:
            return None
        branch = expr.then_expr if condition_value else expr.else_expr
        return analyzer._eval_int_constant_expr(branch, scope)
    if isinstance(expr, CastExpr):
        if not analyzer._is_integer_type(analyzer._resolve_type(expr.type_spec)):
            return None
        return analyzer._eval_int_constant_expr(expr.expr, scope)
    if isinstance(expr, SizeofExpr):
        if expr.type_spec is not None:
            analyzer._register_type_spec(expr.type_spec)
            if analyzer._is_invalid_sizeof_type_spec(expr.type_spec):
                return None
            return analyzer._sizeof_type(analyzer._resolve_type(expr.type_spec))
        if expr.expr is not None:
            operand_type = analyzer._type_map.get(expr.expr)
            if operand_type is None:
                try:
                    operand_type = analyzer._analyze_expr(expr.expr, scope)
                except SemaError:
                    return None
            if operand_type is not None:
                return analyzer._sizeof_type(operand_type)
        return None
    if isinstance(expr, AlignofExpr):
        if expr.type_spec is not None:
            analyzer._register_type_spec(expr.type_spec)
            if analyzer._is_invalid_alignof_type_spec(expr.type_spec):
                return None
            return analyzer._alignof_type(analyzer._resolve_type(expr.type_spec))
        if expr.expr is None:
            return None
        if isinstance(expr.expr, Identifier):
            symbol = scope.lookup(expr.expr.name)
            if isinstance(symbol, VarSymbol) and symbol.alignment is not None:
                return symbol.alignment
        operand_type = analyzer._type_map.get(expr.expr)
        if operand_type is None:
            try:
                operand_type = analyzer._analyze_expr(expr.expr, scope)
            except SemaError:
                return None
        if operand_type is None:
            return None
        return analyzer._alignof_type(operand_type)
    if isinstance(expr, BuiltinOffsetofExpr):
        return None
    if isinstance(expr, BuiltinTypesCompatExpr):
        analyzer._register_type_spec(expr.type1)
        analyzer._register_type_spec(expr.type2)
        type1 = analyzer._unqualified_type(analyzer._resolve_type(expr.type1))
        type2 = analyzer._unqualified_type(analyzer._resolve_type(expr.type2))
        return 1 if type1 == type2 else 0
    if isinstance(expr, GenericExpr):
        return _eval_generic_int_constant_expr(analyzer, expr, scope)
    if isinstance(expr, CommaExpr):
        analyzer._analyze_expr(expr.left, scope)
        return analyzer._eval_int_constant_expr(expr.right, scope)
    if isinstance(expr, Identifier):
        enum_value = scope.lookup_enum_value(expr.name)
        if enum_value is not None:
            return enum_value
        symbol = scope.lookup(expr.name)
        if isinstance(symbol, EnumConstSymbol):
            return symbol.value
        if (
            isinstance(symbol, VarSymbol)
            and symbol.constant_value is not None
            and _allows_const_var_folding(analyzer)
        ):
            return symbol.constant_value
    if isinstance(expr, SubscriptExpr):
        if not _allows_const_var_folding(analyzer):
            return None
        index = analyzer._eval_int_constant_expr(expr.index, scope)
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
                    return analyzer._eval_int_constant_expr(init_val, scope)
    if isinstance(expr, MemberExpr):
        if not _allows_const_var_folding(analyzer):
            return None
        return _eval_member_expr(analyzer, expr, scope)
    return None


def _eval_member_expr(analyzer: "Analyzer", expr: "MemberExpr", scope: Scope) -> int | None:
    """Evaluate a member access expression in a const context."""
    # Evaluate the base expression first
    base_val = analyzer._eval_int_constant_expr(expr.base, scope)
    if base_val is not None:
        # If base is a scalar, the member access resolves to that scalar
        # (scalar initializes struct's first member recursively).
        return base_val
    # If base is an Identifier, resolve the member through the init_list.
    if isinstance(expr.base, Identifier):
        symbol = scope.lookup(expr.base.name)
        if isinstance(symbol, VarSymbol) and symbol._init_expr is not None:
            base_type = symbol.type_
            if isinstance(symbol._init_expr, InitList):
                return _lookup_member_in_init(
                    analyzer, symbol._init_expr, base_type, expr.member, scope
                )
    return None


def _lookup_member_in_init(
    analyzer: "Analyzer",
    init_list: "InitList",
    base_type: Type,
    member_name: str,
    scope: Scope,
) -> int | None:
    """Find a member's initializer value in an InitList."""
    if not analyzer._is_record_name(base_type.name):
        return None
    members = analyzer._record_members(base_type.name)
    if members is None:
        return None
    for idx, m in enumerate(members):
        if m.name == member_name and idx < len(init_list.items):
            item = init_list.items[idx]
            if item.designators:
                return None
            return analyzer._eval_int_constant_expr(item.initializer, scope)  # type: ignore
    return None


def _eval_binary_int_constant_expr(
    analyzer: "Analyzer",
    expr: BinaryExpr,
    scope: Scope,
) -> int | None:
    left_value = analyzer._eval_int_constant_expr(expr.left, scope)
    if left_value is None:
        return None
    if expr.op == "&&":
        if not left_value:
            return 0
        right_value = analyzer._eval_int_constant_expr(expr.right, scope)
        if right_value is None:
            return None
        return 1 if right_value else 0
    if expr.op == "||":
        if left_value:
            return 1
        right_value = analyzer._eval_int_constant_expr(expr.right, scope)
        if right_value is None:
            return None
        return 1 if right_value else 0
    right_value = analyzer._eval_int_constant_expr(expr.right, scope)
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
    analyzer: "Analyzer",
    expr: GenericExpr,
    scope: Scope,
) -> int | None:
    selected_expr: Expr | None = None
    default_expr: Expr | None = None
    control_type = analyzer._type_map.get(expr.control)
    if control_type is None:
        control_type = analyzer._analyze_expr(expr.control, scope)
    control_type = analyzer._decay_array_value(control_type)
    for assoc_type_spec, assoc_expr in expr.associations:
        if assoc_type_spec is None:
            default_expr = assoc_expr
            continue
        analyzer._register_type_spec(assoc_type_spec)
        if analyzer._resolve_type(assoc_type_spec) == control_type:
            selected_expr = assoc_expr
    if selected_expr is None:
        selected_expr = default_expr
    if selected_expr is None:
        return None
    return analyzer._eval_int_constant_expr(selected_expr, scope)


def char_const_value(analyzer: "Analyzer", lexeme: str) -> int | None:
    body = analyzer._char_literal_body(lexeme)
    if body is None:
        return None
    units = analyzer._decode_escaped_units(body)
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


def string_literal_required_length(analyzer: "Analyzer", lexeme: str) -> int | None:
    body = analyzer._string_literal_body(lexeme)
    return None if body is None else len(analyzer._decode_escaped_units(body)) + 1


def string_literal_body(lexeme: str) -> str | None:
    if lexeme.startswith('"') and lexeme.endswith('"'):
        return lexeme[1:-1]
    if lexeme.startswith('u8"') and lexeme.endswith('"'):
        return lexeme[3:-1]
    if (
        len(lexeme) >= 3
        and lexeme[0] in {"u", "U", "L"}
        and lexeme[1] == '"'
        and lexeme.endswith('"')
    ):
        return lexeme[2:-1]
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
