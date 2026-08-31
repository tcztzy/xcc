from typing import TYPE_CHECKING

from xcc.ast import CastExpr, Expr
from xcc.types import INT, VOID, Type

from .symbols import Scope

if TYPE_CHECKING:
    from . import Analyzer


def is_complete_object_pointer_type(a: "Analyzer", type_: Type) -> bool:
    pointee = type_.pointee()
    if pointee is None:
        return False
    if pointee.name == VOID.name and not pointee.declarator_ops:
        return False
    if pointee.declarator_ops and pointee.declarator_ops[0][0] == "fn":
        return False
    return not (a._is_record_name(pointee.name) and a._record_members(pointee.name) is None)


def is_null_pointer_constant(a: "Analyzer", expr: Expr, scope: Scope) -> bool:
    if a._eval_int_constant_expr(expr, scope) == 0:
        return True
    if not isinstance(expr, CastExpr):
        return False
    cast_type = a._type_map.get(expr)
    if cast_type is None:
        cast_type = a._resolve_type(expr.type_spec)
    return a._is_void_pointer_type(cast_type) and a._is_null_pointer_constant(expr.expr, scope)


def is_assignment_expr_compatible(
    a: "Analyzer",
    target_type: Type,
    value_expr: Expr,
    value_type: Type,
    scope: Scope,
) -> bool:
    return a._is_assignment_compatible(target_type, value_type) or (
        target_type.pointee() is not None and a._is_null_pointer_constant(value_expr, scope)
    )


def is_scalar_type(a: "Analyzer", type_: Type) -> bool:
    return a._is_arithmetic_type(type_) or (
        bool(type_.declarator_ops) and type_.declarator_ops[0][0] == "ptr"
    )


def _is_pointer_arithmetic_type(a: "Analyzer", type_: Type) -> bool:
    if a._is_complete_object_pointer_type(type_):
        return True
    pointee = type_.pointee()
    return pointee is not None and pointee.name == VOID.name and not pointee.declarator_ops


def _is_gnu_mode(a: "Analyzer") -> bool:
    return a._std == "gnu11"


def analyze_additive_types(
    a: "Analyzer",
    left_type: Type,
    right_type: Type,
    op: str,
) -> Type | None:
    arithmetic_result = a._usual_arithmetic_conversion(left_type, right_type)
    if arithmetic_result is not None:
        return arithmetic_result
    if op == "+":
        if _is_pointer_arithmetic_type(a, left_type) and a._is_integer_type(right_type):
            return left_type
        if _is_pointer_arithmetic_type(a, right_type) and a._is_integer_type(left_type):
            return right_type
        return None
    if _is_pointer_arithmetic_type(a, left_type) and a._is_integer_type(right_type):
        return left_type
    if a._is_void_pointer_type(left_type) and a._is_void_pointer_type(right_type):
        return INT
    if a._is_compatible_nonvoid_object_pointer_pair(left_type, right_type):
        return INT
    # In GNU mode, allow subtraction of any two complete object pointer types
    if (
        _is_gnu_mode(a)
        and a._is_complete_object_pointer_type(left_type)
        and a._is_complete_object_pointer_type(right_type)
    ):
        return INT
    return None


def is_compatible_nonvoid_object_pointer_pair(
    a: "Analyzer",
    left_type: Type,
    right_type: Type,
) -> bool:
    left_pointee = left_type.pointee()
    right_pointee = right_type.pointee()
    if left_pointee is None or right_pointee is None:
        return False
    if left_pointee.name == VOID.name or right_pointee.name == VOID.name:
        return _is_gnu_mode(a)
    # Function pointer comparison is a GNU extension (accepted in gnu11 mode).
    gnu = _is_gnu_mode(a)
    if left_pointee.declarator_ops and left_pointee.declarator_ops[0][0] == "fn" and not gnu:
        return False
    if right_pointee.declarator_ops and right_pointee.declarator_ops[0][0] == "fn" and not gnu:
        return False
    if a._has_nested_pointer_qualifier_mismatch(left_pointee, right_pointee):
        return False
    return a._is_compatible_pointee_type(left_pointee, right_pointee)


def is_pointer_relational_compatible(
    a: "Analyzer",
    left_type: Type,
    right_type: Type,
) -> bool:
    left_pointee = left_type.pointee()
    right_pointee = right_type.pointee()
    if (
        left_pointee is not None
        and right_pointee is not None
        and left_pointee.name == VOID.name
        and right_pointee.name == VOID.name
        and not left_pointee.declarator_ops
        and not right_pointee.declarator_ops
    ):
        return True
    return a._is_compatible_nonvoid_object_pointer_pair(left_type, right_type)


def is_pointer_equality_compatible(
    a: "Analyzer",
    left_type: Type,
    right_type: Type,
) -> bool:
    if (a._is_void_pointer_type(left_type) and right_type.callable_signature() is not None) or (
        a._is_void_pointer_type(right_type) and left_type.callable_signature() is not None
    ):
        return True
    return a._is_assignment_compatible(left_type, right_type) or a._is_assignment_compatible(
        right_type,
        left_type,
    )


def conditional_pointer_result(
    a: "Analyzer",
    then_expr: Expr,
    then_type: Type,
    else_expr: Expr,
    else_type: Type,
    scope: Scope,
) -> Type | None:
    then_pointee = then_type.pointee()
    else_pointee = else_type.pointee()
    if then_pointee is not None and a._is_null_pointer_constant(else_expr, scope):
        return then_type
    if else_pointee is not None and a._is_null_pointer_constant(then_expr, scope):
        return else_type
    if then_pointee is not None and else_pointee is not None:
        if a._is_compatible_pointee_type(
            then_pointee,
            else_pointee,
        ) and not a._has_nested_pointer_qualifier_mismatch(then_pointee, else_pointee):
            return Type(
                then_type.name,
                declarator_ops=then_type.declarator_ops,
                qualifiers=a._merged_qualifiers(then_pointee, else_pointee),
            )
        if a._is_void_pointer_type(then_type) and a._is_object_pointer_type(else_type):
            return Type(
                VOID.name,
                declarator_ops=then_type.declarator_ops,
                qualifiers=a._merged_qualifiers(then_pointee, else_pointee),
            )
        if a._is_void_pointer_type(else_type) and a._is_object_pointer_type(then_type):
            return Type(
                VOID.name,
                declarator_ops=else_type.declarator_ops,
                qualifiers=a._merged_qualifiers(then_pointee, else_pointee),
            )
        if a._is_void_pointer_type(then_type) and else_type.callable_signature() is not None:
            return Type(
                VOID.name,
                declarator_ops=then_type.declarator_ops,
                qualifiers=a._merged_qualifiers(then_pointee, else_pointee),
            )
        if a._is_void_pointer_type(else_type) and then_type.callable_signature() is not None:
            return Type(
                VOID.name,
                declarator_ops=else_type.declarator_ops,
                qualifiers=a._merged_qualifiers(then_pointee, else_pointee),
            )
        # In GNU mode, any two incompatible pointer types in a
        # conditional expression yield void* (GCC -fpermissive).
        if _is_gnu_mode(a):
            return Type(VOID.name, declarator_ops=(("ptr", 0),))
        return None
    return None
