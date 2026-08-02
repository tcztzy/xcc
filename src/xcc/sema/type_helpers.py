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

SIGNED_INTEGER_TYPE_LIMITS: dict[Type, tuple[int, int]] = {
    INT: (-(1 << 31), (1 << 31) - 1),
    LONG: (-(1 << 63), (1 << 63) - 1),
    LLONG: (-(1 << 63), (1 << 63) - 1),
    INT128: (-(1 << 127), (1 << 127) - 1),
}
UNSIGNED_INTEGER_TYPE_LIMITS: dict[Type, int] = {
    UINT: (1 << 32) - 1,
    ULONG: (1 << 64) - 1,
    ULLONG: (1 << 64) - 1,
    UINT128: (1 << 128) - 1,
    EVM_UINT256: (1 << 256) - 1,
    EVM_ADDRESS: (1 << 160) - 1,
}
INTEGER_PROMOTION_TYPES = {
    BOOL.name: INT,
    CHAR.name: INT,
    UCHAR.name: INT,
    SHORT.name: INT,
    USHORT.name: INT,
}
INTEGER_TYPE_RANKS = {
    BOOL.name: 1,
    CHAR.name: 2,
    UCHAR.name: 2,
    SHORT.name: 3,
    USHORT.name: 3,
    INT.name: 4,
    UINT.name: 4,
    LONG.name: 5,
    ULONG.name: 5,
    LLONG.name: 6,
    ULLONG.name: 6,
    INT128.name: 7,
    UINT128.name: 7,
    EVM_ADDRESS.name: 8,
    EVM_UINT256.name: 9,
}
SIGNED_INTEGER_NAMES = {CHAR.name, SHORT.name, INT.name, LONG.name, LLONG.name, INT128.name}
UNSIGNED_COUNTERPARTS = {
    INT.name: UINT,
    LONG.name: ULONG,
    LLONG.name: ULLONG,
    INT128.name: UINT128,
}
CANONICAL_INTEGER_TYPES = {
    BOOL.name: BOOL,
    CHAR.name: CHAR,
    UCHAR.name: UCHAR,
    SHORT.name: SHORT,
    USHORT.name: USHORT,
    INT.name: INT,
    UINT.name: UINT,
    LONG.name: LONG,
    ULONG.name: ULONG,
    LLONG.name: LLONG,
    ULLONG.name: ULLONG,
    INT128.name: INT128,
    UINT128.name: UINT128,
    EVM_ADDRESS.name: EVM_ADDRESS,
    EVM_UINT256.name: EVM_UINT256,
}


def is_integer_type(type_: Type) -> bool:
    if type_.declarator_ops:
        return False
    return _canonical_integer_type(type_.name) is not None


def is_const_qualified(type_: Type) -> bool:
    return "const" in type_.qualifiers


def is_floating_type(type_: Type) -> bool:
    if type_.declarator_ops:
        return False
    return type_.name in ("float", "double", "long double")


def is_arithmetic_type(type_: Type) -> bool:
    return is_integer_type(type_) or is_floating_type(type_)


def _aot_integer_type_summary() -> str:
    return f"INT={is_integer_type(INT)}|VOID={is_integer_type(VOID)}"


def unqualified_type(type_: Type) -> Type:
    if not type_.qualifiers:
        return type_
    return Type(type_.name, declarator_ops=type_.declarator_ops)


def integer_rank(type_: Type) -> int:
    name = unqualified_type(type_).name
    if name == "_Bool":
        return 1
    if name in ("char", "unsigned char"):
        return 2
    if name in ("short", "unsigned short"):
        return 3
    if name in ("int", "unsigned int"):
        return 4
    if name in ("long", "unsigned long"):
        return 5
    if name in ("long long", "unsigned long long"):
        return 6
    if name in ("__int128", INT128.name, "unsigned __int128", UINT128.name):
        return 7
    if name == "__evm_address":
        return 8
    if name == "__evm_uint256":
        return 9
    return 0


def is_signed_integer_type(type_: Type) -> bool:
    unqualified = unqualified_type(type_)
    return is_integer_type(unqualified) and unqualified.name in (
        "char",
        "short",
        "int",
        "long",
        "long long",
        "__int128",
        INT128.name,
    )


def integer_promotion(type_: Type) -> Type:
    unqualified = unqualified_type(type_)
    if not is_integer_type(unqualified):
        return unqualified
    promoted = _integer_promotion_type(unqualified.name)
    if promoted is not None:
        return promoted
    canonical = _canonical_integer_type(unqualified.name)
    if canonical is not None:
        return canonical
    return unqualified  # pragma: no cover - is_integer_type requires a canonical type.


def signed_range(type_: Type) -> tuple[int, int] | None:
    name = unqualified_type(type_).name
    if name == "int":
        return (-(1 << 31), (1 << 31) - 1)
    if name in ("long", "long long"):
        return (-(1 << 63), (1 << 63) - 1)
    if name in ("__int128", INT128.name):
        return (-(1 << 127), (1 << 127) - 1)
    return None


def unsigned_max(type_: Type) -> int | None:
    name = unqualified_type(type_).name
    if name == "unsigned int":
        return (1 << 32) - 1
    if name in ("unsigned long", "unsigned long long"):
        return (1 << 64) - 1
    if name in ("unsigned __int128", UINT128.name):
        return (1 << 128) - 1
    if name == "__evm_uint256":
        return (1 << 256) - 1
    if name == "__evm_address":
        return (1 << 160) - 1
    return None


def signed_can_represent_unsigned(signed: Type, unsigned: Type) -> bool:
    bounds = signed_range(signed)
    maximum = unsigned_max(unsigned)
    return bounds is not None and maximum is not None and bounds[1] >= maximum


def usual_arithmetic_conversion(left_type: Type, right_type: Type) -> Type | None:
    left_type = unqualified_type(left_type)
    right_type = unqualified_type(right_type)
    if is_floating_type(left_type) or is_floating_type(right_type):
        if left_type.name == "long double" or right_type.name == "long double":
            return LONGDOUBLE
        if left_type.name == "double" or right_type.name == "double":
            return DOUBLE
        return FLOAT
    if not is_integer_type(left_type) or not is_integer_type(right_type):
        return None
    left = integer_promotion(left_type)
    right = integer_promotion(right_type)
    if left == right:
        return left
    left_signed = is_signed_integer_type(left)
    right_signed = is_signed_integer_type(right)
    if left_signed == right_signed:
        return left if integer_rank(left) >= integer_rank(right) else right
    signed_type = left if left_signed else right
    unsigned_type = right if left_signed else left
    if integer_rank(unsigned_type) >= integer_rank(signed_type):
        return unsigned_type
    if signed_can_represent_unsigned(signed_type, unsigned_type):
        return signed_type
    counterpart = _unsigned_counterpart(signed_type.name)
    if counterpart is not None:
        return counterpart
    return unsigned_type  # pragma: no cover - all signed integer types have counterparts here.


def _integer_promotion_type(name: str) -> Type | None:
    if name in ("_Bool", "char", "unsigned char", "short", "unsigned short"):
        return INT
    return None


def _canonical_integer_type(name: str) -> Type | None:
    if name == "_Bool":
        return BOOL
    if name == "char":
        return CHAR
    if name == "unsigned char":
        return UCHAR
    if name == "short":
        return SHORT
    if name == "unsigned short":
        return USHORT
    if name == "int":
        return INT
    if name == "unsigned int":
        return UINT
    if name == "long":
        return LONG
    if name == "unsigned long":
        return ULONG
    if name == "long long":
        return LLONG
    if name == "unsigned long long":
        return ULLONG
    if name == "__int128" or name == INT128.name:
        return INT128
    if name == "unsigned __int128" or name == UINT128.name:
        return UINT128
    if name == "__evm_address":
        return EVM_ADDRESS
    if name == "__evm_uint256":
        return EVM_UINT256
    return None


def _unsigned_counterpart(name: str) -> Type | None:
    if name == "int":
        return UINT
    if name == "long":
        return ULONG
    if name == "long long":
        return ULLONG
    if name == "__int128" or name == INT128.name:
        return UINT128
    return None


def is_void_pointer_type(type_: Type) -> bool:
    pointee = type_.pointee()
    return pointee is not None and pointee.declarator_ops == () and pointee.name == VOID.name


def same_type_structure(left_type: Type, right_type: Type, require_qualifiers: bool) -> bool:
    if left_type.name != right_type.name:
        return False
    if require_qualifiers and left_type.qualifiers != right_type.qualifiers:
        return False
    left_ops = left_type.declarator_ops
    right_ops = right_type.declarator_ops
    if len(left_ops) != len(right_ops):
        return False
    for index in range(len(left_ops)):
        left_kind, left_value = left_ops[index]
        right_kind, right_value = right_ops[index]
        if left_kind != right_kind:
            return False
        if left_kind == "ptr":
            continue
        if left_kind == "arr":
            if not isinstance(left_value, int) or not isinstance(right_value, int):
                return False
            if left_value != right_value:
                return False
            continue
        if left_kind != "fn":
            return False
        if not isinstance(left_value, tuple) or not isinstance(right_value, tuple):
            return False
        left_params, left_variadic = left_value
        right_params, right_variadic = right_value
        if left_variadic != right_variadic:
            return False
        if left_params is None or right_params is None:
            if left_params is not None or right_params is not None:
                return False
            continue
        if len(left_params) != len(right_params):
            return False
        for param_index in range(len(left_params)):
            if not same_type_structure(
                left_params[param_index],
                right_params[param_index],
                True,
            ):
                return False
    return True


def is_compatible_pointee_type(left_type: Type, right_type: Type) -> bool:
    return same_type_structure(left_type, right_type, False)


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


def merged_qualifiers(left_type: Type, right_type: Type) -> tuple[str, ...]:
    return _merge_unique_qualifiers(left_type.qualifiers, right_type.qualifiers)


def qualifiers_contain(target_type: Type, value_type: Type) -> bool:
    for qualifier in value_type.qualifiers:  # noqa: SIM110 - avoid generator lowering in AOT code.
        if qualifier not in target_type.qualifiers:
            return False
    return True


def is_object_pointer_type(type_: Type) -> bool:
    pointee = type_.pointee()
    return pointee is not None and not (
        pointee.declarator_ops and pointee.declarator_ops[0][0] == "fn"
    )


def has_nested_pointer_qualifier_mismatch(left_type: Type, right_type: Type) -> bool:
    return left_type.pointee() is not None and left_type.qualifiers != right_type.qualifiers


def is_pointer_conversion_compatible(target_type: Type, value_type: Type) -> bool:
    target_pointee = target_type.pointee()
    value_pointee = value_type.pointee()
    if target_pointee is None or value_pointee is None:
        return False
    if not is_compatible_pointee_type(target_pointee, value_pointee):
        return False
    if not qualifiers_contain(target_pointee, value_pointee):
        return False
    return not has_nested_pointer_qualifier_mismatch(target_pointee, value_pointee)


def is_assignment_compatible(target_type: Type, value_type: Type) -> bool:
    if same_type_structure(target_type, value_type, True):
        return True
    # Qualifier-only difference for non-pointer/non-array types is compatible
    # (e.g. const struct S value assigned to struct S target).
    # Pointer qualifier compatibility is handled by the pointee checks below.
    if (
        not target_type.declarator_ops
        and target_type.name == value_type.name
        and target_type.declarator_ops == value_type.declarator_ops
    ):
        return True
    if is_arithmetic_type(target_type) and is_arithmetic_type(value_type):
        return True
    target_pointee = target_type.pointee()
    value_pointee = value_type.pointee()
    if target_pointee is None or value_pointee is None:
        return False
    if (is_void_pointer_type(target_type) and value_type.callable_signature() is not None) or (
        is_void_pointer_type(value_type) and target_type.callable_signature() is not None
    ):
        return qualifiers_contain(target_pointee, value_pointee)
    if is_pointer_conversion_compatible(target_type, value_type):
        return True
    if is_void_pointer_type(target_type):
        return is_object_pointer_type(value_type)
    if is_void_pointer_type(value_type):
        return is_object_pointer_type(target_type) and qualifiers_contain(
            target_pointee,
            value_pointee,
        )
    return False
