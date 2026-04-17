from xcc.types import (
    BOOL,
    CHAR,
    DOUBLE,
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

SIGNED_INTEGER_TYPE_LIMITS = {
    INT: (-(1 << 31), (1 << 31) - 1),
    LONG: (-(1 << 63), (1 << 63) - 1),
    LLONG: (-(1 << 63), (1 << 63) - 1),
    INT128: (-(1 << 127), (1 << 127) - 1),
}
UNSIGNED_INTEGER_TYPE_LIMITS = {
    UINT: (1 << 32) - 1,
    ULONG: (1 << 64) - 1,
    ULLONG: (1 << 64) - 1,
    UINT128: (1 << 128) - 1,
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
}


def is_integer_type(type_: Type) -> bool:
    return type_.declarator_ops == () and type_.name in CANONICAL_INTEGER_TYPES


def is_const_qualified(type_: Type) -> bool:
    return "const" in type_.qualifiers


def is_floating_type(type_: Type) -> bool:
    return type_.declarator_ops == () and type_.name in {
        FLOAT.name,
        DOUBLE.name,
        LONGDOUBLE.name,
    }


def is_arithmetic_type(type_: Type) -> bool:
    return is_integer_type(type_) or is_floating_type(type_)


def unqualified_type(type_: Type) -> Type:
    if not type_.qualifiers:
        return type_
    return Type(type_.name, declarator_ops=type_.declarator_ops)


def integer_rank(type_: Type) -> int:
    return INTEGER_TYPE_RANKS[unqualified_type(type_).name]


def is_signed_integer_type(type_: Type) -> bool:
    unqualified = unqualified_type(type_)
    return is_integer_type(unqualified) and unqualified.name in SIGNED_INTEGER_NAMES


def integer_promotion(type_: Type) -> Type:
    unqualified = unqualified_type(type_)
    if not is_integer_type(unqualified):
        return unqualified
    promoted = INTEGER_PROMOTION_TYPES.get(unqualified.name)
    if promoted is not None:
        return promoted
    return CANONICAL_INTEGER_TYPES[unqualified.name]


def signed_range(type_: Type) -> tuple[int, int] | None:
    return SIGNED_INTEGER_TYPE_LIMITS.get(unqualified_type(type_))


def unsigned_max(type_: Type) -> int | None:
    return UNSIGNED_INTEGER_TYPE_LIMITS.get(unqualified_type(type_))


def signed_can_represent_unsigned(signed: Type, unsigned: Type) -> bool:
    bounds = signed_range(signed)
    maximum = unsigned_max(unsigned)
    return bounds is not None and maximum is not None and bounds[1] >= maximum


def usual_arithmetic_conversion(left_type: Type, right_type: Type) -> Type | None:
    left_type = unqualified_type(left_type)
    right_type = unqualified_type(right_type)
    if is_floating_type(left_type) or is_floating_type(right_type):
        if left_type.name == LONGDOUBLE.name or right_type.name == LONGDOUBLE.name:
            return LONGDOUBLE
        if left_type.name == DOUBLE.name or right_type.name == DOUBLE.name:
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
    return UNSIGNED_COUNTERPARTS[signed_type.name]


def is_void_pointer_type(type_: Type) -> bool:
    pointee = type_.pointee()
    return pointee is not None and pointee.declarator_ops == () and pointee.name == VOID.name


def is_compatible_pointee_type(left_type: Type, right_type: Type) -> bool:
    return (
        left_type.name == right_type.name and left_type.declarator_ops == right_type.declarator_ops
    )


def merged_qualifiers(left_type: Type, right_type: Type) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left_type.qualifiers, *right_type.qualifiers)))


def qualifiers_contain(target_type: Type, value_type: Type) -> bool:
    return set(value_type.qualifiers).issubset(target_type.qualifiers)


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
    if target_type == value_type:
        return True
    if is_arithmetic_type(target_type) and is_arithmetic_type(value_type):
        return True
    target_pointee = target_type.pointee()
    value_pointee = value_type.pointee()
    if target_pointee is None or value_pointee is None:
        return False
    if is_pointer_conversion_compatible(target_type, value_type):
        return True
    if is_void_pointer_type(target_type):
        return is_object_pointer_type(value_type) and qualifiers_contain(
            target_pointee,
            value_pointee,
        )
    if is_void_pointer_type(value_type):
        return is_object_pointer_type(target_type) and qualifiers_contain(
            target_pointee,
            value_pointee,
        )
    return False
