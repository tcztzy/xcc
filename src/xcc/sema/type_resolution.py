from typing import TYPE_CHECKING, cast

from xcc.ast import (
    ArrayDecl,
    BinaryExpr,
    CastExpr,
    CharLiteral,
    ConditionalExpr,
    Expr,
    TypeSpec,
    UnaryExpr,
)
from xcc.types import (
    BOOL,
    CHAR,
    DOUBLE,
    EVM_ADDRESS,
    EVM_UINT256,
    FLOAT,
    INT,
    INT128,
    LLONG,
    LONG,
    LONGDOUBLE,
    SHORT,
    UCHAR,
    UINT,
    UINT128,
    ULLONG,
    ULONG,
    USHORT,
    VOID,
    Type,
)

from .constants import char_literal_value
from .symbols import EnumConstSymbol, RecordMemberInfo, Scope, SemaError

if TYPE_CHECKING:
    from . import Analyzer


def register_type_spec(a: "Analyzer", type_spec: TypeSpec) -> None:
    if type_spec.name not in {"struct", "union"}:
        return
    if not type_spec.has_record_body:
        return
    spec_id = id(type_spec)
    if spec_id in a._seen_record_definitions:
        return
    a._seen_record_definitions.add(spec_id)
    key = a._record_type_name(type_spec)
    if type_spec.record_tag is None and a._record_definitions.get(key) is not None:
        return
    seen_members: set[str] = set()
    member_types: list[RecordMemberInfo] = []
    for member in type_spec.record_members:
        member_spec = member.type_spec
        member_name = member.name
        if member_name is not None and member_name in seen_members:
            raise SemaError(f"Duplicate declaration: {member_name}")
        if member_name is not None:
            seen_members.add(member_name)
        if a._is_invalid_void_object_type(member_spec):
            raise SemaError(a._invalid_record_member_type_message("void"))
        if a._is_invalid_atomic_type_spec(member_spec):
            raise SemaError(a._invalid_record_member_type_message("atomic"))
        if a._is_function_object_type(member_spec):
            raise SemaError(a._invalid_record_member_type_message("function"))
        if a._is_invalid_incomplete_record_object_type(member_spec):
            raise SemaError(a._invalid_record_member_type_message("incomplete"))
        # Anonymous enums inside structs define their members at file scope.
        # Use the scoped-enum tracking to prevent duplicate definitions when
        # the same struct is registered multiple times (e.g. via typedef
        # expansion that re-visits the record type).
        if member_spec.name == "enum" and member_spec.enum_members:
            a._define_scoped_enum_members(member_spec, a._file_scope)
        resolved_member_type = a._resolve_type(member_spec)
        bit_width: int | None = None
        if member.bit_width_expr is not None:
            if not a._is_integer_type(resolved_member_type):
                raise SemaError("Bit-field type must be integer")
            bit_width = a._eval_int_constant_expr(member.bit_width_expr, a._file_scope)
            if bit_width is None:
                raise SemaError("Bit-field width is not integer constant")
            if bit_width < 0:
                raise SemaError("Bit-field width must be non-negative")
            max_width = a._sizeof_type(resolved_member_type)
            assert max_width is not None
            if bit_width > max_width * 8:
                raise SemaError("Bit-field width exceeds type width")
            if member_name is not None and bit_width == 0:
                raise SemaError("Named bit-field width must be greater than zero")
        natural_alignment = a._alignof_type(resolved_member_type)
        if not a._is_valid_explicit_alignment(member.alignment, natural_alignment):
            assert member.alignment is not None
            raise SemaError(
                a._invalid_alignment_message(
                    "record member declaration",
                    member.alignment,
                    natural_alignment,
                )
            )
        if (
            member_name is None
            and bit_width is None
            and not resolved_member_type.declarator_ops
            and a._is_record_name(resolved_member_type.name)
        ):
            nested_lookup = a._record_member_lookup(resolved_member_type.name)
            if nested_lookup is not None:
                for nested_name in nested_lookup:
                    if nested_name in seen_members:
                        raise SemaError(f"Duplicate declaration: {nested_name}")
                    seen_members.add(nested_name)
        member_types.append(
            RecordMemberInfo(
                member_name,
                resolved_member_type,
                member.alignment,
                bit_width,
            )
        )
    existing = a._record_definitions.get(key)
    if existing is not None:
        if existing != tuple(member_types):
            display_key = key.split(" <scope:")[0]
            raise SemaError(f"Duplicate definition: {display_key}")
        return
    a._record_definitions[key] = tuple(member_types)
    a._record_layout_cache = {}
    location = a._current_source_location
    pack = None if location is None else a._pack_alignment_for(location.line)
    a._record_pack[key] = pack


def resolve_type(a: "Analyzer", type_spec: TypeSpec) -> Type:
    a._register_type_spec(type_spec)
    ops = type_spec.declarator_ops
    is_unqualified_scalar = not ops and not type_spec.qualifiers
    if type_spec.name == "int" and is_unqualified_scalar:
        return INT
    if type_spec.name == "char" and is_unqualified_scalar:
        return CHAR
    if type_spec.name == "unsigned char" and is_unqualified_scalar:
        return UCHAR
    if type_spec.name in ("_Bool", "bool") and is_unqualified_scalar:
        return BOOL
    if type_spec.name == "short" and is_unqualified_scalar:
        return SHORT
    if type_spec.name == "unsigned short" and is_unqualified_scalar:
        return USHORT
    if type_spec.name == "long" and is_unqualified_scalar:
        return LONG
    if type_spec.name == "unsigned long" and is_unqualified_scalar:
        return ULONG
    if type_spec.name == "long long" and is_unqualified_scalar:
        return LLONG
    if type_spec.name == "unsigned long long" and is_unqualified_scalar:
        return ULLONG
    if type_spec.name == "__int128_t" and is_unqualified_scalar:
        return INT128
    if type_spec.name == "__uint128_t" and is_unqualified_scalar:
        return UINT128
    if type_spec.name == "__evm_uint256" and is_unqualified_scalar:
        return EVM_UINT256
    if type_spec.name == "__evm_address" and is_unqualified_scalar:
        return EVM_ADDRESS
    if type_spec.name == "float" and is_unqualified_scalar:
        return FLOAT
    if type_spec.name == "double" and is_unqualified_scalar:
        return DOUBLE
    if type_spec.name == "long double" and is_unqualified_scalar:
        return LONGDOUBLE
    if type_spec.name == "unsigned int" and is_unqualified_scalar:
        return UINT
    if type_spec.name == "void" and is_unqualified_scalar:
        return VOID
    if type_spec.name == "typeof" and type_spec.typeof_expr is not None:
        scope = a._current_scope if a._current_scope is not None else a._file_scope
        expr_type = a._analyze_expr(type_spec.typeof_expr, scope)
        if ops:
            base = expr_type
            for kind, value in ops:
                if kind == "ptr":
                    base = base.pointer_to()
                elif kind == "arr":
                    bound = a._resolve_array_bound(value)
                    base = base.array_of(bound)
                else:  # pragma: no cover
                    pass
            return base
        return expr_type
    if type_spec.name == "enum" and is_unqualified_scalar:
        return INT
    if type_spec.name in {"struct", "union"} and not ops:
        return Type(a._record_type_name(type_spec), qualifiers=type_spec.qualifiers)
    resolved_ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
    for kind, value in ops:
        if kind == "ptr":
            resolved_ops.append(("ptr", 0))
            continue
        if kind == "arr":
            resolved_ops.append(("arr", a._resolve_array_bound(value)))
            continue
        if kind != "fn":
            assert isinstance(value, int)
            resolved_ops.append((kind, value))
            continue
        assert isinstance(value, tuple) and len(value) == 2
        resolved_params = a._resolve_function_param_types(
            cast(tuple[tuple[TypeSpec, ...] | None, bool], value)
        )
        resolved_ops.append((kind, resolved_params))
    if type_spec.name == "enum":
        base_name = "int"
    elif type_spec.name in {"struct", "union"}:
        base_name = a._record_type_name(type_spec)
    else:
        base_name = type_spec.name
    return Type(base_name, declarator_ops=tuple(resolved_ops), qualifiers=type_spec.qualifiers)


def resolve_array_bound(a: "Analyzer", value: object) -> int:
    if isinstance(value, int):
        return value
    if not isinstance(value, ArrayDecl):
        return -1
    if value.length is None:
        return -1
    if isinstance(value.length, int):
        return value.length
    evaluated = a._eval_int_constant_expr(value.length, a._file_scope)
    if evaluated is None:
        return -1
    return evaluated


def resolve_function_param_types(
    a: "Analyzer",
    declarator_value: int | tuple[tuple[TypeSpec, ...] | None, bool],
) -> tuple[tuple[Type, ...] | None, bool]:
    assert isinstance(declarator_value, tuple) and len(declarator_value) == 2
    param_specs, is_variadic = declarator_value
    if param_specs is None:
        if is_variadic:
            raise SemaError("Variadic function requires a prototype")
        return None, False
    params: list[Type] = []
    for param_spec in param_specs:
        if a._is_invalid_atomic_type_spec(param_spec):
            raise SemaError("Invalid parameter type: atomic")
        if a._is_invalid_void_parameter_type(param_spec):
            raise SemaError("Invalid parameter type: void")
        if a._is_invalid_incomplete_record_object_type(param_spec):
            raise SemaError("Invalid parameter type: incomplete")
        params.append(a._resolve_param_type(param_spec))
    return tuple(params), is_variadic


def resolve_param_type(a: "Analyzer", type_spec: TypeSpec) -> Type:
    resolved = a._resolve_type(type_spec)
    return resolved.decay_parameter_type()


def define_enum_members(a: "Analyzer", type_spec: TypeSpec, scope: Scope) -> None:
    next_value = 0
    for name, expr in type_spec.enum_members:
        enum_value = next_value
        if expr is not None:
            evaluated = _eval_enum_int_constant_expr(a, expr, scope)
            if evaluated is None:
                raise SemaError("Enumerator value is not integer constant")
            enum_value = evaluated
        scope.define(EnumConstSymbol(name, enum_value))
        next_value = enum_value + 1


def _eval_enum_int_constant_expr(a: "Analyzer", expr: Expr, scope: Scope) -> int | None:
    value = a._eval_int_constant_expr(expr, scope)
    if value is not None:
        return value
    if isinstance(expr, CharLiteral):
        return char_literal_value(expr.value)
    if isinstance(expr, CastExpr):
        if not a._is_integer_type(a._resolve_type(expr.type_spec)):
            return None
        return _eval_enum_int_constant_expr(a, expr.expr, scope)
    if isinstance(expr, UnaryExpr) and expr.op in {"+", "-", "!", "~"}:
        operand = _eval_enum_int_constant_expr(a, expr.operand, scope)
        if operand is None:
            return None
        if expr.op == "+":
            return operand
        if expr.op == "-":
            return -operand
        if expr.op == "!":
            return 0 if operand else 1
        return ~operand
    if isinstance(expr, ConditionalExpr):
        condition = _eval_enum_int_constant_expr(a, expr.condition, scope)
        if condition is None:
            return None
        return _eval_enum_int_constant_expr(
            a,
            expr.then_expr if condition else expr.else_expr,
            scope,
        )
    if isinstance(expr, BinaryExpr):
        return _eval_enum_binary_int_constant_expr(a, expr, scope)
    return None


def _eval_enum_binary_int_constant_expr(
    a: "Analyzer",
    expr: BinaryExpr,
    scope: Scope,
) -> int | None:
    left = _eval_enum_int_constant_expr(a, expr.left, scope)
    if left is None:
        return None
    if expr.op == "&&":
        if not left:
            return 0
        right = _eval_enum_int_constant_expr(a, expr.right, scope)
        return None if right is None else int(bool(right))
    if expr.op == "||":
        if left:
            return 1
        right = _eval_enum_int_constant_expr(a, expr.right, scope)
        return None if right is None else int(bool(right))
    right = _eval_enum_int_constant_expr(a, expr.right, scope)
    if right is None:
        return None
    if expr.op == "+":
        return left + right
    if expr.op == "-":
        return left - right
    if expr.op == "*":
        return left * right
    if expr.op == "/":
        return None if right == 0 else left // right
    if expr.op == "%":
        return None if right == 0 else left % right
    if expr.op == "<<":
        return None if right < 0 else left << right
    if expr.op == ">>":
        return None if right < 0 else left >> right
    if expr.op == "<":
        return int(left < right)
    if expr.op == "<=":
        return int(left <= right)
    if expr.op == ">":
        return int(left > right)
    if expr.op == ">=":
        return int(left >= right)
    if expr.op == "==":
        return int(left == right)
    if expr.op == "!=":
        return int(left != right)
    if expr.op == "&":
        return left & right
    if expr.op == "^":
        return left ^ right
    if expr.op == "|":
        return left | right
    return None


def define_scoped_enum_members(a: "Analyzer", type_spec: TypeSpec, scope: Scope) -> None:
    if not type_spec.enum_members:
        return
    binding = (id(scope), id(type_spec))
    if binding in a._seen_scoped_enum_definitions:
        return
    a._seen_scoped_enum_definitions.add(binding)
    a._define_enum_members(type_spec, scope)


def is_function_object_type(type_spec: TypeSpec) -> bool:
    ops = type_spec.declarator_ops
    return bool(ops) and ops[0][0] == "fn"


def is_invalid_atomic_type_spec(a: "Analyzer", type_spec: TypeSpec) -> bool:
    if not type_spec.is_atomic:
        return False
    target = type_spec
    if type_spec.atomic_target is not None:
        target = type_spec.atomic_target
    target_ops = target.declarator_ops
    return (
        a._is_invalid_void_object_type(target)
        or a._is_invalid_incomplete_record_object_type(target)
        or a._is_function_object_type(target)
        or (bool(target_ops) and target_ops[0][0] == "arr")
    )


def is_invalid_incomplete_record_object_type(a: "Analyzer", type_spec: TypeSpec) -> bool:
    if type_spec.name not in {"struct", "union"}:
        return False
    ops = type_spec.declarator_ops
    index = 0
    while index < len(ops):
        kind, _ = ops[index]
        if kind == "ptr":
            return False
        index += 1
    if type_spec.record_members:
        return False
    if type_spec.record_tag is None:
        return True
    key = a._record_type_name(type_spec)
    return a._record_members(key) is None


def is_record_name(name: str) -> bool:
    return name.startswith("struct ") or name.startswith("union ")


def lookup_record_member(a: "Analyzer", record_type: Type, member_name: str) -> Type:
    lookup = a._record_member_lookup(record_type.name)
    if lookup is None:
        raise SemaError("Member access on incomplete type")
    member = lookup.get(member_name)
    if member is not None:
        return member[0]
    raise SemaError(f"No such member: {member_name}")


def resolve_member_type(
    a: "Analyzer",
    base_type: Type,
    member_name: str,
    through_pointer: bool,
) -> Type:
    if through_pointer:
        base_value_type = a._decay_array_value(base_type)
        record_type = base_value_type.pointee()
        if (
            record_type is None
            or record_type.declarator_ops
            or not a._is_record_name(record_type.name)
        ):
            # In GNU mode, allow -> on a non-pointer record type by
            # treating it as . (dot) access.  This handles type-system
            # edge cases where a typedef-to-pointer is resolved as the
            # underlying record type.
            if (
                a._std == "gnu11"
                and not base_type.declarator_ops
                and a._is_record_name(base_type.name)
            ):
                return a._lookup_record_member(base_type, member_name)
            raise SemaError("Member access on non-record pointer")
        return a._lookup_record_member(record_type, member_name)
    if base_type.declarator_ops or not a._is_record_name(base_type.name):
        raise SemaError("Member access on non-record type")
    return a._lookup_record_member(base_type, member_name)


def invalid_sizeof_operand_reason_for_type_spec(
    a: "Analyzer",
    type_spec: TypeSpec,
) -> str | None:
    if a._is_invalid_atomic_type_spec(type_spec):
        return "atomic type"
    if a._is_invalid_void_object_type(type_spec):
        return "void type"
    if a._is_invalid_incomplete_record_object_type(type_spec):
        return "incomplete type"
    if a._is_function_object_type(type_spec):
        return "function type"
    return None


def invalid_sizeof_operand_reason_for_type(a: "Analyzer", type_: Type) -> str | None:
    if type_ == VOID:
        return "void type"
    ops = type_.declarator_ops
    if ops and ops[0][0] == "fn":
        return "function type"
    index = 0
    while index < len(ops):
        kind, _ = ops[index]
        if kind == "ptr":
            return None
        index += 1
    if a._is_record_name(type_.name) and a._record_members(type_.name) is None:
        return "incomplete type"
    return None


def invalid_generic_association_type_reason(
    a: "Analyzer",
    type_spec: TypeSpec,
) -> str | None:
    sizeof_reason = a._invalid_sizeof_operand_reason_for_type_spec(type_spec)
    if sizeof_reason is not None:
        return sizeof_reason
    if a._is_variably_modified_type_spec(type_spec):
        return "variably modified type"
    return None


def describe_generic_association_type(type_spec: TypeSpec, resolved_type: Type) -> str:
    spelled_type = f"{' '.join(type_spec.qualifiers)} {type_spec.name}".strip()
    if not type_spec.declarator_ops and not type_spec.is_atomic:
        return spelled_type
    return str(resolved_type)


def is_variably_modified_type_spec(a: "Analyzer", type_spec: TypeSpec) -> bool:
    for kind, value in type_spec.declarator_ops:
        if kind != "arr":
            continue
        if isinstance(value, int):
            if value < 0:
                return True
            continue
        if not isinstance(value, ArrayDecl):
            return True
        if value.length is None:
            return True
        if isinstance(value.length, int):
            continue
        if a._eval_int_constant_expr(value.length, a._file_scope) is None:
            return True
    return False


def is_valid_explicit_alignment(alignment: int | None, natural_alignment: int | None) -> bool:
    if alignment is None:
        return True
    if alignment <= 0 or (alignment & (alignment - 1)) != 0:
        return False
    return natural_alignment is not None and alignment >= natural_alignment
